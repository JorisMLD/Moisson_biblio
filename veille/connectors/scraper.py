"""Connecteur scraper (regime 3) : sites de revues sans API.

Contrairement aux connecteurs OAI et metadata, il n'y a pas de format
standard : le code depend du HTML reel de chaque site. Un parseur par
plateforme, derriere un meme contrat.

Parseurs disponibles :
- FLM (flm-journal.org) : numero courant (`do=current`), resume sur la page
  `do=details&ArtID=...`. Texte integral sous abonnement (acces ouvert differe
  de 3 ans), donc pas de PDF libre.
- IREM Grenoble (Petit x, Grand N, Reperes IREM) : page de consultation, puis
  page de chaque numero, puis page de chaque article (auteurs, PDF).

Couche HTTP injectable (`http_get`) pour les tests hors ligne.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .. import http
from ..models import RawRecord, WorkType
from .base import Connector

log = logging.getLogger("veille")

ISSUE_RE = re.compile(r"Vol\.\s*(\d+)\s*Num\.\s*(\d+)\s*\((\d{4})\)")

HttpGetText = Callable[[str], str]


def _default_http_get_text(url: str) -> str:
    # Identite de navigateur : ces sites repondent mal a un client trop nu.
    return http.fetch(url, as_="text", browser=True)


class ScraperConnector(Connector):
    name = "scraper"

    def __init__(
        self,
        http_get: Optional[HttpGetText] = None,
        *,
        enrich_abstracts: bool = True,
        page_pause: float = 0.5,
        irem_incremental_issues: int = 4,
    ) -> None:
        self._get = http_get or _default_http_get_text
        self._enrich = enrich_abstracts
        self._page_pause = page_pause
        self._irem_incr = irem_incremental_issues

    def fetch_new(
        self, source: sqlite3.Row, since: Optional[datetime]
    ) -> Iterator[RawRecord]:
        base = (source["base_url"] or "").rstrip("/")
        host = urlsplit(base).netloc
        if "flm-journal.org" in host:
            yield from self._fetch_flm(source, base)
        elif "irem.univ-grenoble-alpes.fr" in host:
            yield from self._fetch_irem(source, base, since)
        else:
            raise NotImplementedError(f"aucun parseur scraper pour l'hote '{host}'")

    # --- FLM : For the Learning of Mathematics -----------------------------

    def _fetch_flm(self, source: sqlite3.Row, base: str) -> Iterator[RawRecord]:
        """Moissonne le numero courant. Le sommaire courant est en do=current ;
        le resume de chaque article est sur sa page do=details."""
        index = f"{base}/index.php"
        home = self._get(f"{index}?do=current&lang=en")
        year_map = _flm_year_map(home)
        current = max(year_map) if year_map else None
        journal = source["name"]

        for art in _flm_parse_toc(home, current):
            year = year_map.get((art["vol"], art["num"]))
            abstract = None
            details_url = None
            if art["details"]:
                details_url = urljoin(index + "?", art["details"])
                if self._enrich:
                    abstract = self._flm_abstract(details_url)
            yield RawRecord(
                source_id=source["id"],
                external_id=art["external_id"],
                title=art["title"],
                authors=art["authors"],
                year=year,
                journal=journal,
                doi=None,
                abstract=abstract,
                full_text_url=details_url,
            )

    def _flm_abstract(self, details_url: str) -> Optional[str]:
        try:
            time.sleep(self._page_pause)
            html = self._get(details_url)
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            m = re.search(r"ABSTRACT:\s*(.+?)\s*(?:Go Back|$)", text, flags=re.S)
            if not m:
                return None
            return " ".join(m.group(1).split())
        except Exception:
            return None

    # --- IREM Grenoble : Petit x, Grand N, Reperes IREM -------------------

    def _fetch_irem(
        self, source: sqlite3.Row, base: str, since: Optional[datetime]
    ) -> Iterator[RawRecord]:
        """Moissonne la page de consultation, puis descend au grain de l'article.

        Les trois revues partagent la meme plateforme (K-Sup, URLs en .kjsp). La
        page de consultation liste les numeros ; chaque page de numero reutilise
        la meme classe `liste__objets__titre` pour lister ses articles. On se
        sert de l'identifiant .kjsp final comme cle stable, ce qui neutralise les
        variations d'URL selon l'epoque.

        - enrich actif (defaut) : on descend dans chaque numero pour lister les
          articles, puis dans chaque article pour ses auteurs (DC.Creator) et son
          PDF (a.fichiers-joints__lien, range dans oa_url). Un hors-serie sans
          liste retombe sur une entree au grain du numero. Premier passage complet
          couteux : un fetch par article ; --no-enrich pour un backfill rapide.
        - enrich inactif (--no-enrich) : grain du numero seulement, un seul fetch
          par revue.

        Le resume n'est pas expose par ces pages (il ne vit que dans le PDF).
        L'annee est celle du numero : la date de page (DC.Date) vaut l'annee de
        mise en ligne, pas celle de publication.
        """
        path = (source["consultation_path"] or "").lstrip("/")
        url = urljoin(base + "/", path)
        html = self._get(url)
        journal = source["name"]

        issues = _irem_parse_listing(html)
        if since is not None:
            issues = issues[: self._irem_incr]  # incrementiel : numeros recents

        log.info("  %s : %d numéro(s) à parcourir", journal, len(issues))
        for n, iss in enumerate(issues, 1):
            if n % 10 == 0:
                log.info("  ... %s : %d / %d numéros", journal, n, len(issues))
            if not self._enrich:
                yield _irem_record(source["id"], journal, iss, iss["year"], issue=True)
                continue
            articles: list[dict] = []
            try:
                time.sleep(self._page_pause)
                articles = _irem_parse_listing(self._get(iss["url"]))
            except Exception:
                articles = []
            if not articles:  # hors-serie / page brute : on garde le numero
                yield _irem_record(source["id"], journal, iss, iss["year"], issue=True)
                continue
            for art in articles:
                authors, pdf = self._irem_article_details(art["url"])
                yield _irem_record(source["id"], journal, art, iss["year"],
                                   authors=authors, oa_url=pdf)

    def _irem_article_details(self, url: str) -> tuple[list[str], Optional[str]]:
        """Recupere auteurs (DC.Creator) et URL du PDF sur une page d'article."""
        try:
            time.sleep(self._page_pause)
            soup = BeautifulSoup(self._get(url), "html.parser")
            authors = _irem_authors(soup)
            a = soup.select_one("a.fichiers-joints__lien")
            pdf = a.get("href") if a and a.get("href") else None
            return authors, pdf
        except Exception:
            return [], None


# --- Fonctions de parsing IREM (testables hors ligne) ----------------------

IREM_NUM_RE = re.compile(r"Num[ée]ro\s+(\d+(?:[-\u2013]\d+)?)", re.I)
IREM_YEAR_RE = re.compile(r"\((\d{4})\)")
IREM_KJSP_RE = re.compile(r"-(\d+)\.kjsp", re.I)


def _irem_authors(soup: BeautifulSoup) -> list[str]:
    """Auteurs depuis les meta DC.Creator (une balise par auteur en general).
    On ecarte les valeurs institutionnelles parasites (ex. l'universite)."""
    out: list[str] = []
    for m in soup.find_all("meta", attrs={"name": "DC.Creator"}):
        c = " ".join((m.get("content") or "").split())
        if c and c not in out and "universit" not in c.lower():
            out.append(c)
    return out


def _irem_record(
    source_id: int,
    journal: str,
    item: dict,
    year: Optional[int],
    authors: Optional[list[str]] = None,
    oa_url: Optional[str] = None,
    issue: bool = False,
) -> RawRecord:
    """Construit un RawRecord a partir d'une entree IREM (numero ou article).
    L'annee est celle du numero, propagee aux articles qui n'en portent pas.
    oa_url porte l'URL de telechargement du PDF (acces ouvert)."""
    return RawRecord(
        source_id=source_id,
        external_id=item["external_id"],
        title=item["title"],
        authors=authors or [],
        year=item["year"] if item["year"] is not None else year,
        journal=journal,
        doi=None,
        abstract=None,
        full_text_url=item["url"],
        oa_url=oa_url,
        work_type=(WorkType.ISSUE if issue else WorkType.ARTICLE).value,
    )


def _irem_parse_listing(html: str) -> list[dict]:
    """Extrait les numeros d'une page de consultation IREM Grenoble.

    On cible la liste de contenu via la classe `liste__objets__titre`, ce qui
    ecarte d'office les liens du plan de site (classe `lien_interne` seule).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for a in soup.select("a.liste__objets__titre"):
        href = a.get("href")
        if not href:
            continue
        label = " ".join(a.get_text(" ", strip=True).split())
        if not label:
            continue
        mnum = IREM_NUM_RE.search(label)
        myear = IREM_YEAR_RE.search(label)
        mid = IREM_KJSP_RE.search(href)
        ext = (
            f"iremgren:{mid.group(1)}" if mid
            else "iremgren:" + re.sub(r"\W+", "-", label.lower())[:50]
        )
        out.append({
            "external_id": ext,
            "title": label,
            "year": int(myear.group(1)) if myear else None,
            "number": mnum.group(1) if mnum else None,
            "url": href,
        })
    return out


# --- Fonctions de parsing FLM (testables hors ligne) -----------------------

def _flm_year_map(html: str) -> dict[tuple[int, int], int]:
    """Construit (vol, num) -> annee depuis la liste des numeros de la page."""
    out: dict[tuple[int, int], int] = {}
    for vol, num, year in ISSUE_RE.findall(html):
        out[(int(vol), int(num))] = int(year)
    return out


def _flm_clean_title(text: str) -> str:
    text = re.sub(r"^\s*Communication:\s*", "", text)
    return " ".join(text.split())


def _flm_parse_toc(html: str, current: Optional[tuple[int, int]]) -> list[dict]:
    """Extrait les articles d'un sommaire FLM.

    On classe les liens par leur href (stable, contrairement a la mise en
    page) : do=search = auteur, do=subscribe2_to_flm = titre (texte du lien),
    do=details = page de detail (donne ArtID, vol, num, pages).
    """
    soup = BeautifulSoup(html, "html.parser")
    articles: list[dict] = []
    pending_authors: list[str] = []
    current_art: Optional[dict] = None

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if "do=search" in href and "search=" in href:
            if text and text != "-":
                pending_authors.append(text)
        elif "do=subscribe2_to_flm" in href:
            title = _flm_clean_title(text)
            low = title.lower()
            if not title or low in ("front cover", "contributors", "back cover"):
                pending_authors = []
                current_art = None
                continue
            cur = current or (0, 0)
            current_art = {
                "title": title, "authors": pending_authors,
                "vol": cur[0], "num": cur[1], "details": None,
                "external_id": f"flm:{cur[0]}:{cur[1]}:" + re.sub(r"\W+", "-", low)[:60],
            }
            articles.append(current_art)
            pending_authors = []
        elif "do=details" in href and current_art is not None:
            current_art["details"] = href
            qs = parse_qs(urlsplit(href).query)
            if "vol" in qs:
                current_art["vol"] = int(qs["vol"][0])
            if "num" in qs:
                current_art["num"] = int(qs["num"][0])
            if "ArtID" in qs:
                current_art["external_id"] = f"flm:art:{qs['ArtID'][0]}"

    return articles
