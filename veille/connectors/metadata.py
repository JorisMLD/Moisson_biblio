"""Connecteur metadonnees : Crossref par ISSN, repli OpenAlex pour le resume.

Pour les revues et series bien referencees, souvent sous abonnement (ESM, ZDM,
JRME, JMB, AJME, RDM, New ICMI Study Series). On obtient titre, auteurs, DOI,
type de document, references et resume quand l'editeur l'a depose dans
Crossref. Sans resume Crossref, on tente OpenAlex a partir du DOI, qui le
reconstruit depuis son index inverse (interrogation par DOI : gratuite).

Couche HTTP injectable (parametre `get_json`) pour des tests hors ligne.
"""

from __future__ import annotations

import html
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Optional

from .. import config, http
from ..models import RawRecord, WorkType
from .base import Connector

log = logging.getLogger("veille")

CROSSREF_URL = "https://api.crossref.org/works"
OPENALEX_WORK_URL = "https://api.openalex.org/works"

# Champs demandes a Crossref, pour alleger les reponses.
# 'language' n'est PAS un champ autorise ici : l'inclure renvoie un 400.
CROSSREF_SELECT = "DOI,title,author,editor,issued,container-title,type,abstract,reference"

_TYPES = {
    "journal-article": WorkType.ARTICLE,
    "book-chapter": WorkType.CHAPTER,
    "book-part": WorkType.CHAPTER,
    "book-section": WorkType.CHAPTER,
    "book": WorkType.BOOK,
    "edited-book": WorkType.BOOK,
    "monograph": WorkType.BOOK,
}

GetJson = Callable[[str, dict], dict]


def _default_get_json(url: str, params: dict) -> dict:
    return http.fetch(url, params, as_="json")


def openalex_params(extra: Optional[dict] = None) -> dict:
    """Parametres d'identification OpenAlex : email et cle si configures."""
    s = config.get()
    p: dict = {}
    if s.email:
        p["mailto"] = s.email
    if s.openalex_api_key:
        p["api_key"] = s.openalex_api_key
    if extra:
        p.update(extra)
    return p


def _clean_jats(text: Optional[str]) -> Optional[str]:
    """Nettoie un resume Crossref, souvent encode en JATS XML."""
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(Abstract|Résumé|Resume)\s*[:.]?\s+", "", text, flags=re.I)
    return text or None


def _reconstruct_abstract(inverted: Optional[dict]) -> Optional[str]:
    """Reconstruit un resume depuis l'index inverse d'OpenAlex."""
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


class MetadataConnector(Connector):
    name = "metadata"

    def __init__(
        self,
        get_json: Optional[GetJson] = None,
        *,
        mailto: Optional[str] = None,
        rows: int = 200,
        enrich_abstracts: bool = True,
        page_pause: float = 0.5,
    ) -> None:
        self._get_json = get_json or _default_get_json
        self._mailto = mailto if mailto is not None else config.get().email
        self._rows = rows
        self._enrich = enrich_abstracts
        self._page_pause = page_pause

    def fetch_new(self, source: sqlite3.Row, since: Optional[datetime]) -> Iterator[RawRecord]:
        issns = [i for i in (source["issn_print"], source["issn_online"]) if i]
        if not issns:
            raise ValueError(f"source '{source['name']}' sans ISSN")

        # Filtres Crossref : les ISSN sont combines en OU, la date en ET.
        # from-index-date capte aussi les notices reindexees (mises a jour).
        filters = [f"issn:{i}" for i in issns]
        if since is not None:
            filters.append(f"from-index-date:{since.date().isoformat()}")
        params = {
            "filter": ",".join(filters),
            "rows": str(self._rows),
            "cursor": "*",
            "select": CROSSREF_SELECT,
        }
        if self._mailto:
            params["mailto"] = self._mailto
        yield from self._harvest_crossref(params, source["id"])

    def _harvest_crossref(self, params: dict, source_id: int) -> Iterator[RawRecord]:
        first = True
        seen = 0
        while True:
            if not first:
                time.sleep(self._page_pause)
            first = False
            data = self._get_json(CROSSREF_URL, params)
            message = data.get("message", {})
            items = message.get("items", [])
            if not items:
                return
            total = message.get("total-results")
            for item in items:
                rec = self._parse_item(item, source_id)
                if rec is None:
                    continue
                if self._enrich and not rec.abstract and rec.doi:
                    rec.abstract = self._openalex_abstract(rec.doi)
                yield rec
            seen += len(items)
            if total and total > self._rows:
                log.info("  ... %d / %d notices Crossref", min(seen, total), total)
            cursor = message.get("next-cursor")
            if not cursor:
                return
            params = dict(params, cursor=cursor)

    def _parse_item(self, item: dict, source_id: int) -> Optional[RawRecord]:
        titles = item.get("title") or []
        if not titles:
            return None
        doi = item.get("DOI")
        raw_type = item.get("type")
        wtype = _TYPES.get(raw_type, WorkType.OTHER) if raw_type else WorkType.ARTICLE
        people = item.get("author") or []
        if not people and wtype == WorkType.BOOK:
            people = item.get("editor") or []
        return RawRecord(
            source_id=source_id,
            external_id=doi or titles[0],
            title=" ".join(titles[0].split()),
            authors=self._authors(people),
            year=self._year(item),
            journal=(item.get("container-title") or [None])[0],
            doi=doi,
            abstract=_clean_jats(item.get("abstract")),
            references=self._references(item.get("reference", [])),
            language=item.get("language"),
            work_type=wtype.value,
        )

    @staticmethod
    def _authors(authors: list[dict]) -> list[str]:
        out: list[str] = []
        for a in authors:
            if a.get("family"):
                out.append(f"{a['family']}, {a['given']}" if a.get("given") else a["family"])
            elif a.get("name"):
                out.append(a["name"])
        return out

    @staticmethod
    def _year(item: dict) -> Optional[int]:
        parts = (item.get("issued") or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
        return None

    @staticmethod
    def _references(refs: list[dict]) -> list[str]:
        out: list[str] = []
        for r in refs:
            if r.get("unstructured"):
                out.append(" ".join(r["unstructured"].split()))
                continue
            parts = [
                r.get("author"),
                r.get("year"),
                r.get("article-title") or r.get("volume-title") or r.get("journal-title"),
                f"DOI:{r['DOI']}" if r.get("DOI") else None,
            ]
            joined = ", ".join(str(p) for p in parts if p)
            if joined:
                out.append(joined)
        return out

    def _openalex_abstract(self, doi: str) -> Optional[str]:
        """Repli best-effort : un echec ne fait jamais tomber le moissonnage."""
        try:
            time.sleep(self._page_pause)
            data = self._get_json(f"{OPENALEX_WORK_URL}/doi:{doi}", openalex_params())
            return _reconstruct_abstract(data.get("abstract_inverted_index"))
        except Exception:
            return None
