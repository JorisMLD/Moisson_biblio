"""Connecteur OAI-PMH generique.

Un seul code pour toutes les plateformes qui exposent un entrepot OAI :
OpenEdition, Episciences, et les revues sous OJS. Il gere la pagination par
resumptionToken, le moissonnage selectif par date (verbe ListRecords avec
`from` et `set`), et le parsing du format Dublin Core (oai_dc).

La couche HTTP est injectable (parametre `http_get`) pour permettre des tests
hors ligne avec des fixtures XML.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Optional

from .. import http
from ..models import RawRecord
from .base import Connector

log = logging.getLogger("veille")

OAI = "{http://www.openarchives.org/OAI/2.0/}"
OAIDC = "{http://www.openarchives.org/OAI/2.0/oai_dc/}"
DC = "{http://purl.org/dc/elements/1.1/}"

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
YEAR_RE = re.compile(r"(1[89]\d{2}|20\d{2})")

# Type de la fonction HTTP injectable : (base_url, params) -> corps XML.
HttpGet = Callable[[str, dict[str, str]], str]


class OaiError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"OAI error [{code}]: {message}")
        self.code = code


def _default_http_get(base_url: str, params: dict[str, str]) -> str:
    return http.fetch(base_url, params, as_="text")


class OaiConnector(Connector):
    name = "oai"

    def __init__(self, http_get: Optional[HttpGet] = None, page_pause: float = 0.5) -> None:
        self._http_get = http_get or _default_http_get
        self._page_pause = page_pause

    # --- API du connecteur -------------------------------------------------

    def fetch_new(
        self, source: sqlite3.Row, since: datetime | None
    ) -> Iterator[RawRecord]:
        base_url = source["base_url"]
        if not base_url:
            raise ValueError(f"source '{source['name']}' sans base_url OAI")
        prefix = source["metadata_prefix"] or "oai_dc"
        if prefix != "oai_dc":
            raise NotImplementedError(
                f"format '{prefix}' non gere ; ce connecteur ne lit que oai_dc"
            )

        params: dict[str, str] = {"verb": "ListRecords", "metadataPrefix": prefix}
        if source["oai_set"]:
            params["set"] = source["oai_set"]
        if since is not None:
            # OAI `from` est inclusif ; granularite jour, suffisante et la plus
            # largement supportee. La deduplication absorbe les recouvrements.
            params["from"] = since.date().isoformat()

        yield from self._harvest(base_url, params, source["id"])

    # --- Mecanique OAI -----------------------------------------------------

    def _harvest(
        self, base_url: str, first_params: dict[str, str], source_id: int
    ) -> Iterator[RawRecord]:
        params = first_params
        first = True
        pages = 0
        while True:
            if not first:
                time.sleep(self._page_pause)
            first = False
            xml = self._http_get(base_url, params)
            root = ET.fromstring(xml)

            err = root.find(f"{OAI}error")
            if err is not None:
                code = err.get("code", "unknown")
                if code == "noRecordsMatch":
                    return  # aucune nouveaute : fin normale
                raise OaiError(code, (err.text or "").strip())

            lr = root.find(f"{OAI}ListRecords")
            if lr is None:
                return
            pages += 1
            if pages % 10 == 0:
                log.info("  ... %d pages OAI lues", pages)
            for rec in lr.findall(f"{OAI}record"):
                parsed = self._parse_record(rec, source_id)
                if parsed is not None:
                    yield parsed

            token_el = lr.find(f"{OAI}resumptionToken")
            token = (token_el.text or "").strip() if token_el is not None else ""
            if not token:
                return
            # Apres le premier appel, seuls verb + resumptionToken sont permis.
            params = {"verb": "ListRecords", "resumptionToken": token}

    def _parse_record(self, rec: ET.Element, source_id: int) -> Optional[RawRecord]:
        header = rec.find(f"{OAI}header")
        if header is None:
            return None
        external_id = (header.findtext(f"{OAI}identifier") or "").strip()
        datestamp = (header.findtext(f"{OAI}datestamp") or "").strip() or None

        if header.get("status") == "deleted":
            return RawRecord(
                source_id=source_id, external_id=external_id, title="",
                datestamp=datestamp, deleted=True,
            )

        dc = None
        meta = rec.find(f"{OAI}metadata")
        if meta is not None:
            dc = meta.find(f"{OAIDC}dc")
        if dc is None:
            return None

        def values(tag: str) -> list[str]:
            return [(e.text or "").strip() for e in dc.findall(f"{DC}{tag}") if (e.text or "").strip()]

        titles = values("title")
        if not titles:
            return None
        identifiers = values("identifier")
        relations = values("relation")
        descriptions = values("description")
        dates = values("date")
        sources = values("source")
        langs = values("language")

        doi = self._first_doi(identifiers + relations)
        full_text_url = next((i for i in identifiers if i.startswith("http")), None)

        return RawRecord(
            source_id=source_id,
            external_id=doi or external_id,
            title=" ".join(titles[0].split()),
            authors=values("creator"),
            year=self._first_year(dates),
            journal=sources[0] if sources else None,
            doi=doi,
            abstract=max(descriptions, key=len) if descriptions else None,
            full_text_url=full_text_url,
            # dc:relation contient des liens (numero, ISSN, version), pas la
            # bibliographie : oai_dc ne porte pas les references. On laisse la
            # liste vide pour que la commande `references` puisse la completer.
            references=[],
            language=langs[0] if langs else None,
            datestamp=datestamp,
        )

    @staticmethod
    def _first_doi(candidates: list[str]) -> Optional[str]:
        for c in candidates:
            m = DOI_RE.search(c)
            if m:
                return m.group(0).rstrip(".")
        return None

    @staticmethod
    def _first_year(dates: list[str]) -> Optional[int]:
        for d in dates:
            m = YEAR_RE.search(d)
            if m:
                return int(m.group(0))
        return None

    # --- Decouverte d'entrepot (verbes Identify / ListSets) ----------------

    def identify(self, base_url: str) -> dict[str, str]:
        xml = self._http_get(base_url, {"verb": "Identify"})
        root = ET.fromstring(xml)
        node = root.find(f"{OAI}Identify")
        out: dict[str, str] = {}
        if node is not None:
            for child in node:
                tag = child.tag.replace(OAI, "")
                if child.text and child.text.strip():
                    out[tag] = child.text.strip()
        return out

    def list_sets(self, base_url: str) -> list[tuple[str, str]]:
        """Renvoie [(setSpec, setName), ...] en suivant les resumptionToken."""
        params: dict[str, str] = {"verb": "ListSets"}
        out: list[tuple[str, str]] = []
        while True:
            xml = self._http_get(base_url, params)
            root = ET.fromstring(xml)
            ls = root.find(f"{OAI}ListSets")
            if ls is None:
                break
            for s in ls.findall(f"{OAI}set"):
                spec = (s.findtext(f"{OAI}setSpec") or "").strip()
                name = (s.findtext(f"{OAI}setName") or "").strip()
                out.append((spec, name))
            token_el = ls.find(f"{OAI}resumptionToken")
            token = (token_el.text or "").strip() if token_el is not None else ""
            if not token:
                break
            params = {"verb": "ListSets", "resumptionToken": token}
            time.sleep(self._page_pause)
        return out
