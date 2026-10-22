"""Couche base de donnees : schema, deduplication, persistance.

Tout passe par SQLite (module standard sqlite3), suffisant pour une veille
mono-utilisateur. Le schema ci-dessous est la seule reference : il est cree a
la premiere connexion, et les colonnes ajoutees au fil des versions sont
migrees automatiquement sur une base existante.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .models import SOURCE_RANK, FileKind, RawRecord, normalize_doi

SCHEMA = """
-- Registre des revues : une ligne par source. Alimente par sources.seed.json.
CREATE TABLE IF NOT EXISTS sources (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    connector         TEXT NOT NULL,            -- 'oai' | 'metadata' | 'scraper'
    issn_print        TEXT,
    issn_online       TEXT,
    base_url          TEXT,                     -- entrepot OAI, ou URL de base d'un site
    oai_set           TEXT,                     -- setSpec OAI (optionnel)
    metadata_prefix   TEXT NOT NULL DEFAULT 'oai_dc',
    consultation_path TEXT,                     -- page de consultation (scraper IREM)
    enabled           INTEGER NOT NULL DEFAULT 1,
    last_run          TEXT,                     -- ISO 8601 UTC du dernier passage reussi
    notes             TEXT
);

-- Les notices. Deduplication par DOI (normalise) quand il existe, sinon par
-- empreinte (titre normalise + annee + revue).
CREATE TABLE IF NOT EXISTS works (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES sources(id),
    external_id     TEXT,
    doi             TEXT,
    fingerprint     TEXT NOT NULL,
    title           TEXT NOT NULL,
    authors_json    TEXT NOT NULL DEFAULT '[]',
    year            INTEGER,
    journal         TEXT,
    abstract        TEXT,
    language        TEXT,
    work_type       TEXT NOT NULL DEFAULT 'journal-article',
    oa_status       TEXT,
    refs_json       TEXT NOT NULL DEFAULT '[]',
    pdf_checked_at  TEXT,                       -- derniere recherche de PDF (resolve)
    refs_checked_at TEXT,                       -- derniere recherche de references
    first_seen      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_works_doi ON works(doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_works_fingerprint ON works(fingerprint);
CREATE INDEX IF NOT EXISTS idx_works_first_seen ON works(first_seen);

-- Liens rattaches a une notice : page editeur, PDF libre, version auteur HAL.
-- `path` n'est rempli que si le PDF a ete telecharge (commande download).
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    work_id     INTEGER NOT NULL REFERENCES works(id),
    path        TEXT,
    url         TEXT,
    kind        TEXT NOT NULL,                  -- 'publisher' | 'oa' | 'hal_author'
    source_rank INTEGER NOT NULL,
    fetched_at  TEXT,
    UNIQUE(work_id, kind)
);

-- Journal des passages, une ligne par source et par mise a jour.
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER REFERENCES sources(id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    n_new       INTEGER NOT NULL DEFAULT 0,
    n_updated   INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'ok',
    message     TEXT
);
"""

# Colonnes ajoutees apres la premiere version : (table, colonne, definition).
_MIGRATIONS = [
    ("works", "work_type", "TEXT NOT NULL DEFAULT 'journal-article'"),
    ("works", "pdf_checked_at", "TEXT"),
    ("works", "refs_checked_at", "TEXT"),
]


def now_utc() -> str:
    """Horodatage ISO 8601 en UTC, sans microsecondes."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def days_ago_utc(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Ouvre la base et garantit un schema a jour (creation ou migration)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, definition in _MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    # Les anciennes versions ne normalisaient pas la casse des DOI.
    conn.execute("UPDATE OR IGNORE works SET doi = lower(doi) WHERE doi <> lower(doi)")
    conn.commit()


# Conserve pour compatibilite : la creation est desormais faite a la connexion.
init_db = ensure_schema


# --- Deduplication ---------------------------------------------------------

def _normalize(s: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces compactes."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def fingerprint(title: str, year: Optional[int], journal: Optional[str]) -> str:
    base = f"{_normalize(title)}|{year or ''}|{_normalize(journal or '')}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


# --- Sources ---------------------------------------------------------------

_SOURCE_COLS = [
    "name", "connector", "issn_print", "issn_online", "base_url",
    "oai_set", "metadata_prefix", "consultation_path", "enabled", "notes",
]


def get_enabled_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY id"))


def count_sources(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])


def set_last_run(conn: sqlite3.Connection, source_id: int, ts: str) -> None:
    conn.execute("UPDATE sources SET last_run = ? WHERE id = ?", (ts, source_id))
    conn.commit()


def upsert_source(conn: sqlite3.Connection, **fields: object) -> int:
    """Insere ou met a jour une source, identifiee par son nom. Renvoie son id.
    Le champ last_run n'est jamais touche : recharger le fichier de sources ne
    relance pas de moissonnage complet."""
    row = conn.execute("SELECT id FROM sources WHERE name = ?", (fields["name"],)).fetchone()
    vals = {c: fields.get(c) for c in _SOURCE_COLS}
    if vals["metadata_prefix"] is None:
        vals["metadata_prefix"] = "oai_dc"
    if vals["enabled"] is None:
        vals["enabled"] = 1
    if row is None:
        placeholders = ", ".join("?" for _ in _SOURCE_COLS)
        cur = conn.execute(
            f"INSERT INTO sources ({', '.join(_SOURCE_COLS)}) VALUES ({placeholders})",
            [vals[c] for c in _SOURCE_COLS],
        )
        conn.commit()
        return int(cur.lastrowid)
    assignments = ", ".join(f"{c} = ?" for c in _SOURCE_COLS)
    conn.execute(f"UPDATE sources SET {assignments} WHERE id = ?",
                 [vals[c] for c in _SOURCE_COLS] + [row["id"]])
    conn.commit()
    return int(row["id"])


def load_seed(conn: sqlite3.Connection, seed_path: str | Path) -> list[tuple[int, dict]]:
    entries = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    return [(upsert_source(conn, **e), e) for e in entries]


# --- Notices ---------------------------------------------------------------

def upsert_work(conn: sqlite3.Connection, rec: RawRecord) -> tuple[int, str]:
    """Insere ou enrichit une notice. Renvoie (work_id, 'new'|'updated').

    Recherche d'abord par DOI s'il existe, sinon par empreinte. En cas de
    correspondance, on complete les champs manquants sans ecraser l'existant.
    """
    rec.doi = normalize_doi(rec.doi)
    fp = fingerprint(rec.title, rec.year, rec.journal or "")
    if rec.doi:
        existing = conn.execute("SELECT * FROM works WHERE doi = ?", (rec.doi,)).fetchone()
        if existing is None:
            # DOI inconnu : on ne fusionne qu'avec une notice deja vue SANS DOI.
            # Une empreinte identique mais un autre DOI designe une notice
            # distincte (editoriaux, pages de garde d'une meme annee).
            existing = conn.execute(
                "SELECT * FROM works WHERE fingerprint = ? AND doi IS NULL", (fp,)
            ).fetchone()
    else:
        existing = conn.execute("SELECT * FROM works WHERE fingerprint = ?", (fp,)).fetchone()

    ts = now_utc()
    if existing is None:
        cur = conn.execute(
            """INSERT INTO works
               (source_id, external_id, doi, fingerprint, title, authors_json, year,
                journal, abstract, language, work_type, refs_json, first_seen, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec.source_id, rec.external_id, rec.doi, fp, rec.title,
             json.dumps(rec.authors, ensure_ascii=False), rec.year, rec.journal,
             rec.abstract, rec.language, rec.work_type,
             json.dumps(rec.references, ensure_ascii=False), ts, ts),
        )
        conn.commit()
        return int(cur.lastrowid), "new"

    updates: dict[str, object] = {}
    if not existing["doi"] and rec.doi:
        updates["doi"] = rec.doi
    if not existing["abstract"] and rec.abstract:
        updates["abstract"] = rec.abstract
    if not existing["language"] and rec.language:
        updates["language"] = rec.language
    if json.loads(existing["refs_json"]) == [] and rec.references:
        updates["refs_json"] = json.dumps(rec.references, ensure_ascii=False)
    if json.loads(existing["authors_json"]) == [] and rec.authors:
        updates["authors_json"] = json.dumps(rec.authors, ensure_ascii=False)
    if updates:
        updates["updated_at"] = ts
        assignments = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE works SET {assignments} WHERE id = ?",
                     list(updates.values()) + [existing["id"]])
        conn.commit()
    return int(existing["id"]), "updated"


def add_file(
    conn: sqlite3.Connection,
    work_id: int,
    *,
    kind: FileKind,
    url: Optional[str] = None,
    path: Optional[str] = None,
    fetched_at: Optional[str] = None,
) -> None:
    """Rattache un lien a une notice (un par type), sans degrader un lien de
    meilleur rang deja present."""
    rank = SOURCE_RANK[kind]
    conn.execute(
        """INSERT INTO files (work_id, path, url, kind, source_rank, fetched_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(work_id, kind) DO UPDATE SET
             url = COALESCE(excluded.url, files.url),
             path = COALESCE(excluded.path, files.path),
             fetched_at = COALESCE(excluded.fetched_at, files.fetched_at)
           WHERE excluded.source_rank <= files.source_rank""",
        (work_id, path, url, kind.value, rank, fetched_at),
    )
    conn.commit()


def mark_checked(conn: sqlite3.Connection, column: str, work_ids: Sequence[int]) -> None:
    """Note qu'une recherche (PDF ou references) a ete faite pour ces notices,
    qu'elle ait abouti ou non, pour ne pas la refaire au passage suivant."""
    if column not in ("pdf_checked_at", "refs_checked_at"):
        raise ValueError(column)
    ts = now_utc()
    ids = list(work_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        conn.execute(
            f"UPDATE works SET {column} = ? WHERE id IN ({','.join('?' * len(chunk))})",
            [ts, *chunk],
        )
    conn.commit()


# --- Journal des passages --------------------------------------------------

def start_run(conn: sqlite3.Connection, source_id: int) -> int:
    cur = conn.execute("INSERT INTO runs (source_id, started_at) VALUES (?, ?)",
                       (source_id, now_utc()))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, *, n_new: int, n_updated: int,
               status: str = "ok", message: Optional[str] = None) -> None:
    conn.execute(
        """UPDATE runs SET finished_at = ?, n_new = ?, n_updated = ?,
                           status = ?, message = ? WHERE id = ?""",
        (now_utc(), n_new, n_updated, status, message, run_id),
    )
    conn.commit()


def new_works_since(conn: sqlite3.Connection, since_iso: str) -> Iterable[sqlite3.Row]:
    """Notices vues pour la premiere fois depuis un horodatage (pour le digest)."""
    return conn.execute(
        "SELECT * FROM works WHERE first_seen >= ? ORDER BY journal, year DESC, title",
        (since_iso,),
    )


# --- Selections pour resolve, references, download, export ----------------

def _recheck_clause(column: str, recheck_days: Optional[int]) -> tuple[str, list]:
    if recheck_days is None:
        return f"w.{column} IS NULL", []
    return f"(w.{column} IS NULL OR w.{column} <= ?)", [days_ago_utc(recheck_days)]


def works_without_free_pdf(
    conn: sqlite3.Connection,
    *,
    min_year: Optional[int] = None,
    require_doi: bool = False,
    recheck_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[sqlite3.Row]:
    """Notices sans lien de PDF libre, pas encore examinees (ou examinees il y a
    plus de `recheck_days` jours). Les plus recentes d'abord."""
    clause, params = _recheck_clause("pdf_checked_at", recheck_days)
    where = [
        "NOT EXISTS (SELECT 1 FROM files f WHERE f.work_id = w.id"
        " AND f.kind IN ('oa', 'hal_author') AND f.url IS NOT NULL)",
        clause,
        "w.work_type <> 'issue'",
    ]
    if min_year:
        where.append("w.year IS NOT NULL AND w.year >= ?")
        params.append(min_year)
    if require_doi:
        where.append("w.doi IS NOT NULL")
    sql = f"SELECT * FROM works w WHERE {' AND '.join(where)} ORDER BY w.year DESC, w.id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def works_missing_references(
    conn: sqlite3.Connection,
    *,
    min_year: Optional[int] = None,
    recheck_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[sqlite3.Row]:
    """Notices a DOI sans references, pas encore examinees."""
    clause, params = _recheck_clause("refs_checked_at", recheck_days)
    where = ["w.doi IS NOT NULL", "w.refs_json = '[]'", clause]
    if min_year:
        where.append("w.year IS NOT NULL AND w.year >= ?")
        params.append(min_year)
    sql = f"SELECT * FROM works w WHERE {' AND '.join(where)} ORDER BY w.year DESC, w.id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def set_references(conn: sqlite3.Connection, work_id: int, refs: list[str]) -> None:
    conn.execute(
        "UPDATE works SET refs_json = ?, refs_checked_at = ?, updated_at = ? WHERE id = ?",
        (json.dumps(refs, ensure_ascii=False), now_utc(), now_utc(), work_id),
    )
    conn.commit()


def works_pending_download(
    conn: sqlite3.Connection, min_year: int, limit: Optional[int] = None
) -> list[sqlite3.Row]:
    """Notices a telecharger : un lien de PDF libre, pas encore de fichier local,
    annee >= seuil. On retient la meilleure source (revue avant version HAL)."""
    sql = (
        "SELECT w.id AS work_id, w.external_id, w.doi, w.title, w.year,"
        "       f.url AS file_url, f.kind AS file_kind, f.source_rank "
        "FROM works w JOIN files f ON f.work_id = w.id "
        "WHERE f.kind IN ('oa', 'hal_author') AND f.url IS NOT NULL"
        "  AND f.path IS NULL AND w.year IS NOT NULL AND w.year >= ?"
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM files f2 WHERE f2.work_id = w.id"
        "      AND f2.kind IN ('oa', 'hal_author') AND f2.url IS NOT NULL"
        "      AND f2.source_rank < f.source_rank) "
        "ORDER BY w.year DESC, f.source_rank, w.id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (min_year,)).fetchall()


def works_for_export(
    conn: sqlite3.Connection,
    *,
    min_year: Optional[int] = None,
    journal: Optional[str] = None,
    source_id: Optional[int] = None,
    new_since: Optional[str] = None,
    with_pdf: bool = False,
    limit: Optional[int] = None,
) -> list[sqlite3.Row]:
    """Notices pour export, avec leur meilleur lien PDF libre et leur page
    editeur. Filtres optionnels."""
    where = ["1=1"]
    params: list = []
    if min_year is not None:
        where.append("w.year IS NOT NULL AND w.year >= ?")
        params.append(min_year)
    if journal:
        where.append("w.journal = ?")
        params.append(journal)
    if source_id is not None:
        where.append("w.source_id = ?")
        params.append(source_id)
    if new_since:
        where.append("w.first_seen >= ?")
        params.append(new_since)
    pdf_sub = ("(SELECT f.url FROM files f WHERE f.work_id = w.id"
               " AND f.kind IN ('oa','hal_author') AND f.url IS NOT NULL"
               " ORDER BY f.source_rank LIMIT 1)")
    landing_sub = ("(SELECT f.url FROM files f WHERE f.work_id = w.id"
                   " AND f.kind = 'publisher' AND f.url IS NOT NULL LIMIT 1)")
    if with_pdf:
        where.append(f"{pdf_sub} IS NOT NULL")
    sql = (f"SELECT w.*, s.name AS source_name, {pdf_sub} AS pdf_url,"
           f" {landing_sub} AS landing_url"
           f" FROM works w JOIN sources s ON s.id = w.source_id"
           f" WHERE {' AND '.join(where)} ORDER BY w.year DESC, w.id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def stats(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Bilan par source : notices, liens PDF, references, dernier passage."""
    return conn.execute(
        """SELECT s.id, s.name, s.connector, s.enabled, s.last_run,
                  COUNT(w.id) AS n_works,
                  SUM(CASE WHEN EXISTS (SELECT 1 FROM files f WHERE f.work_id = w.id
                        AND f.kind IN ('oa','hal_author')) THEN 1 ELSE 0 END) AS n_pdf,
                  SUM(CASE WHEN w.refs_json <> '[]' THEN 1 ELSE 0 END) AS n_refs
           FROM sources s LEFT JOIN works w ON w.source_id = s.id
           GROUP BY s.id ORDER BY s.id"""
    ).fetchall()
