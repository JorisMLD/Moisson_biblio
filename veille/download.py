"""Telechargement des PDF, etape separee, optionnelle et volontairement bridee.

Par choix, la veille ne stocke pas les PDF : place disque, et respect des
statistiques de visite des revues (on cite et on lit chez l'editeur). Cette
commande sert a une recolte ponctuelle et deliberee : elle ne prend que les
notices recentes (annee >= seuil) qui ont un lien de PDF libre et pas encore de
fichier local, verifie que le contenu recu est bien un PDF, et note le chemin.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from . import db, http
from .models import FileKind

log = logging.getLogger("veille")

GetBytes = Callable[[str], bytes]


def _default_get_bytes(url: str) -> bytes:
    return http.fetch(url, as_="bytes", browser=True, attempts=3)


def _safe_name(stem: str) -> str:
    return re.sub(r"[^\w.-]+", "_", stem).strip("_")[:120] or "fichier"


def download_pdfs(
    conn: sqlite3.Connection,
    out_dir: str | Path,
    *,
    min_year: int = 2026,
    get_bytes: Optional[GetBytes] = None,
    limit: Optional[int] = None,
    page_pause: float = 1.0,
) -> tuple[int, int]:
    """Telecharge les PDF eligibles. Renvoie (eligibles, reussis)."""
    get_bytes = get_bytes or _default_get_bytes
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = db.works_pending_download(conn, min_year, limit=limit)
    ok = 0
    for r in rows:
        try:
            time.sleep(page_pause)
            data = get_bytes(r["file_url"])
        except Exception as exc:
            log.info("  échec : %s (%s)", r["title"][:60], exc)
            continue
        if not data[:1024].lstrip().startswith(b"%PDF"):
            log.info("  pas un PDF (accès restreint ?) : %s", r["title"][:60])
            continue
        name = _safe_name(r["doi"] or r["external_id"] or f"notice{r['work_id']}") + ".pdf"
        path = out / name
        path.write_bytes(data)
        db.add_file(conn, r["work_id"], kind=FileKind(r["file_kind"]),
                    url=r["file_url"], path=str(path), fetched_at=db.now_utc())
        ok += 1
    return len(rows), ok
