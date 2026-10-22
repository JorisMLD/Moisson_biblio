"""Resolution des liens de PDF en acces ouvert, sans rien telecharger.

Pour chaque notice sans lien de PDF libre et pas encore examinee :
  0. DOI OpenEdition (10.4000) : l'URL du PDF se deduit du DOI, sans requete.
  1. OpenAlex, par lots de 50 DOI par requete -> PDF en acces ouvert (`oa`).
  2. HAL, par lots aussi, pour ce qu'OpenAlex n'a pas trouve -> version
     auteur (`hal_author`, rang 2 : la revue d'abord, HAL en secours).
  3. Optionnellement, notices sans DOI : recherche par titre (rendement faible,
     et payante chez OpenAlex au-dela du forfait gratuit).

Chaque notice examinee est datee (pdf_checked_at), trouvee ou non : le passage
suivant ne la reinterroge pas, sauf au-dela du delai `recheck_days` (un article
peut passer en acces ouvert a la fin d'un embargo).

Tarification OpenAlex (2026) : une interrogation par DOI est gratuite, une
requete filtree (nos lots) coute tres peu ; sans cle, le forfait quotidien
couvre environ mille lots, soit cinquante mille DOI. Si le quota est epuise
(erreur 429 persistante), l'etape OpenAlex s'arrete proprement : les notices
non traitees restent a examiner au passage suivant.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from typing import Optional

from . import db, http
from .connectors.metadata import openalex_params
from .models import FileKind, normalize_doi

log = logging.getLogger("veille")

OPENALEX_WORKS = "https://api.openalex.org/works"
HAL_SEARCH = "https://api.archives-ouvertes.fr/search/"

GetJson = Callable[[str, dict], dict]

# Conserve pour compatibilite avec d'anciens imports.
_norm_doi = normalize_doi


def _default_get_json(url: str, params: dict) -> dict:
    # Peu d'essais : un 429 persistant chez OpenAlex signale un quota epuise.
    return http.fetch(url, params, as_="json", attempts=3, max_wait=60.0)


def openedition_pdf_url(doi: Optional[str]) -> Optional[str]:
    """URL du PDF OpenEdition deduite d'un DOI 10.4000/<revue>.<numero>.

    Ex : 10.4000/educationdidactique.10190 ->
         https://journals.openedition.org/educationdidactique/pdf/10190
    Pour une revue en acces freemium, ce PDF n'est ouvert que depuis une
    institution abonnee ; la commande download ecarte ce qui n'est pas un PDF."""
    d = normalize_doi(doi)
    if not d or not d.startswith("10.4000/"):
        return None
    slug, _, num = d[len("10.4000/"):].rpartition(".")
    if not slug or not num.isdigit():
        return None
    return f"https://journals.openedition.org/{slug}/pdf/{num}"


def openalex_pdf_url(work: dict) -> Optional[str]:
    """URL d'un PDF en acces ouvert dans un objet OpenAlex, ou None.

    On ne retient que des champs `pdf_url` de localisations ouvertes : le champ
    open_access.oa_url pointe souvent vers une page d'accueil, pas un PDF."""
    cands = [(work.get("best_oa_location") or {}).get("pdf_url")]
    primary = work.get("primary_location") or {}
    if primary.get("is_oa"):
        cands.append(primary.get("pdf_url"))
    for loc in work.get("locations") or []:
        if loc.get("is_oa"):
            cands.append(loc.get("pdf_url"))
    return next((c for c in cands if c), None)


def hal_pdf_url(data: dict) -> Optional[str]:
    """URL du fichier principal (PDF) du premier document d'une reponse HAL."""
    for d in (data.get("response") or {}).get("docs") or []:
        url = d.get("fileMain_s") or next(iter(d.get("files_s") or []), None)
        if url:
            return url
    return None


class QuotaExceeded(RuntimeError):
    pass


class PdfUrlResolver:
    def __init__(self, get_json: Optional[GetJson] = None, *, page_pause: float = 0.34) -> None:
        self._get_json = get_json or _default_get_json
        self._page_pause = page_pause

    def openalex_batch(self, dois: list[str]) -> dict[str, Optional[str]]:
        """Interroge OpenAlex pour un lot de DOI (au plus 100). Renvoie
        {doi: url_pdf_ou_None} pour les DOI connus d'OpenAlex.

        Les DOI contenant un caractere qui casserait le filtre (virgule, barre
        verticale) passent par une interrogation individuelle, gratuite ; de
        meme pour tout le lot si OpenAlex le refuse comme invalide (400).
        Leve QuotaExceeded si OpenAlex refuse durablement (429)."""
        norm = [d for d in (normalize_doi(x) for x in dois) if d]
        safe = [d for d in norm if not any(c in d for c in ",|\"")]
        odd = [d for d in norm if d not in safe]
        out: dict[str, Optional[str]] = {}
        if safe:
            time.sleep(self._page_pause)
            try:
                data = self._get_json(OPENALEX_WORKS, openalex_params({
                    "filter": "doi:" + "|".join(safe),
                    "per-page": str(len(safe)),
                    "select": "doi,best_oa_location,primary_location,locations",
                }))
                for w in data.get("results") or []:
                    d = normalize_doi(w.get("doi"))
                    if d:
                        out[d] = openalex_pdf_url(w)
            except http.HttpError as exc:
                if exc.status == 429:
                    raise QuotaExceeded(str(exc)) from exc
                if exc.status != 400:
                    raise
                odd = norm
        for d in odd:
            out[d] = self.openalex_one(d)
        return out

    def openalex_one(self, doi: str) -> Optional[str]:
        """Interrogation individuelle par DOI (gratuite chez OpenAlex)."""
        time.sleep(self._page_pause)
        try:
            w = self._get_json(f"{OPENALEX_WORKS}/doi:{doi}", openalex_params())
        except http.HttpError as exc:
            if exc.status == 429:
                raise QuotaExceeded(str(exc)) from exc
            return None
        return openalex_pdf_url(w)

    def hal_batch(self, dois: list[str]) -> dict[str, str]:
        """Interroge HAL pour un lot de DOI. Renvoie {doi: url_pdf} pour ceux
        qui ont un fichier depose."""
        norm = [d for d in (normalize_doi(x) for x in dois) if d]
        if not norm:
            return {}
        time.sleep(self._page_pause)
        q = "doiId_s:(" + " OR ".join(f'"{d}"' for d in norm) + ")"
        data = self._get_json(HAL_SEARCH, {
            "q": q, "fq": "submitType_s:file",
            "fl": "doiId_s,fileMain_s,files_s", "rows": str(len(norm)), "wt": "json",
        })
        out: dict[str, str] = {}
        for d in (data.get("response") or {}).get("docs") or []:
            doi = normalize_doi(d.get("doiId_s"))
            url = d.get("fileMain_s") or next(iter(d.get("files_s") or []), None)
            if doi and url:
                out.setdefault(doi, url)
        return out

    def by_title(self, work: sqlite3.Row) -> Optional[tuple[FileKind, str]]:
        """Recherche par titre pour une notice sans DOI (OpenAlex puis HAL)."""
        title = work["title"]
        if not title:
            return None
        try:
            time.sleep(self._page_pause)
            res = self._get_json(OPENALEX_WORKS, openalex_params({
                "filter": f"title.search:{title.replace(',', ' ')}", "per-page": "1",
            }))
            first = next(iter(res.get("results") or []), None)
            url = openalex_pdf_url(first) if first else None
            if url:
                return FileKind.OA, url
        except http.HttpError:
            pass
        try:
            authors = json.loads(work["authors_json"] or "[]")
            q = f'title_t:"{title}"'
            if authors:
                q += f' AND authFullName_t:"{authors[0]}"'
            time.sleep(self._page_pause)
            url = hal_pdf_url(self._get_json(HAL_SEARCH, {
                "q": q, "fq": "submitType_s:file",
                "fl": "fileMain_s,files_s", "rows": "1", "wt": "json"}))
            if url:
                return FileKind.HAL_AUTHOR, url
        except http.HttpError:
            pass
        return None


def resolve_pdf_urls(
    conn: sqlite3.Connection,
    resolver: Optional[PdfUrlResolver] = None,
    *,
    limit: Optional[int] = None,
    page_pause: float = 0.34,
    require_doi: bool = True,
    min_year: Optional[int] = 2000,
    recheck_days: Optional[int] = 180,
    batch_size: int = 50,
) -> tuple[int, int]:
    """Cherche des liens de PDF libres. Renvoie (notices examinees, liens trouves)."""
    resolver = resolver or PdfUrlResolver(page_pause=page_pause)
    works = db.works_without_free_pdf(conn, min_year=min_year, require_doi=require_doi,
                                      recheck_days=recheck_days, limit=limit)
    doi_works = [w for w in works if w["doi"]]
    nodoi_works = [w for w in works if not w["doi"]]
    if works:
        log.info("recherche de PDF : %d notice(s) à examiner", len(works))

    found = 0
    examined = 0

    def record(w, kind: FileKind, url: str) -> None:
        nonlocal found
        db.add_file(conn, w["id"], kind=kind, url=url)
        found += 1

    # 0) OpenEdition, sans requete
    rest: list[sqlite3.Row] = []
    oe_ids: list[int] = []
    for w in doi_works:
        url = openedition_pdf_url(w["doi"])
        if url:
            record(w, FileKind.OA, url)
            oe_ids.append(w["id"])
        else:
            rest.append(w)
    db.mark_checked(conn, "pdf_checked_at", oe_ids)
    examined += len(oe_ids)

    # 1) OpenAlex puis 2) HAL, lot par lot
    n_batches = (len(rest) + batch_size - 1) // batch_size
    for b, i in enumerate(range(0, len(rest), batch_size), 1):
        chunk = rest[i:i + batch_size]
        try:
            oa = resolver.openalex_batch([w["doi"] for w in chunk])
        except QuotaExceeded:
            log.warning("OpenAlex refuse de nouvelles requêtes (quota du jour atteint ?). "
                        "Arrêt : les %d notice(s) restantes seront examinées au prochain "
                        "passage. Une clé OpenAlex gratuite relève ce quota (voir le "
                        "mode d'emploi).", len(rest) - i)
            break
        except http.HttpError as exc:
            log.warning("lot OpenAlex ignoré (%s) ; il sera repris au prochain passage", exc)
            continue
        missing: list[sqlite3.Row] = []
        for w in chunk:
            url = oa.get(normalize_doi(w["doi"]))
            if url:
                record(w, FileKind.OA, url)
            else:
                missing.append(w)
        hal_ok = True
        if missing:
            try:
                hal = resolver.hal_batch([w["doi"] for w in missing])
            except http.HttpError as exc:
                log.warning("lot HAL ignoré (%s)", exc)
                hal, hal_ok = {}, False
            for w in missing:
                url = hal.get(normalize_doi(w["doi"]))
                if url:
                    record(w, FileKind.HAL_AUTHOR, url)
        missing_ids = {w["id"] for w in missing}
        checked = [w["id"] for w in chunk if hal_ok or w["id"] not in missing_ids]
        db.mark_checked(conn, "pdf_checked_at", checked)
        examined += len(checked)
        if b % 10 == 0 or b == n_batches:
            log.info("  ... lot %d / %d, %d lien(s) trouvé(s) jusqu'ici", b, n_batches, found)

    # 3) sans DOI, uniquement si demande
    if not require_doi:
        for w in nodoi_works:
            res = resolver.by_title(w)
            if res:
                record(w, *res)
            db.mark_checked(conn, "pdf_checked_at", [w["id"]])
            examined += 1

    return examined, found
