"""Interface en ligne de commande de la veille.

Pour un usage courant, deux commandes suffisent :
    python -m veille setup      premiere installation (base, revues, email)
    python -m veille routine    mise a jour complete (a relancer quand on veut)
ou, sans rien taper, le menu :
    python -m veille menu

Commandes detaillees :
    setup       cree la base, charge les revues, enregistre l'email de contact
    routine     update + resolve + references + export, en une fois
    menu        menu interactif (utilise par les lanceurs Windows/Mac/Linux)
    update      moissonne les revues actives depuis leur dernier passage
    resolve     cherche des liens de PDF en acces ouvert (OpenEdition, OpenAlex, HAL)
    references  complete les bibliographies via Crossref
    export      exporte en BibTeX et/ou en liste de liens PDF
    download    telecharge des PDF recents (usage ponctuel et delibere)
    sources     liste les revues ; stats : bilan par revue
    check       verifie que Crossref repond pour les revues `metadata`
    discover    explore un entrepot OAI (pour ajouter une revue)

Toutes les donnees personnelles (base, reglages, digests, exports) vivent dans
le dossier `donnees/`, ignore par git.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import __version__, config, db, http
from .connectors import MetadataConnector, OaiConnector, ScraperConnector
from .models import FileKind

log = logging.getLogger("veille")

CONNECTORS = {
    "oai": OaiConnector,
    "metadata": MetadataConnector,
    "scraper": ScraperConnector,
}

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = ROOT / "sources.seed.json"
DEFAULT_DB = Path("donnees") / "veille.db"


def _data_dir(args: argparse.Namespace) -> Path:
    return Path(args.db).resolve().parent


def _connect(args: argparse.Namespace) -> sqlite3.Connection:
    Path(args.db).resolve().parent.mkdir(parents=True, exist_ok=True)
    return db.connect(args.db)


def _parse_since(last_run: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(last_run) if last_run else None


# --- Installation ----------------------------------------------------------

def _ask_email(args: argparse.Namespace, *, force: bool = False) -> None:
    """Demande l'email de contact s'il manque (ou si force), puis l'enregistre."""
    settings = config.get()
    if settings.email and not force:
        return
    if not sys.stdin.isatty() or getattr(args, "no_prompt", False):
        return
    print("\nCrossref et OpenAlex demandent une adresse de contact. Elle n'est")
    print("envoyée qu'à ces services et reste dans donnees/config.json.")
    current = f" [{settings.email}]" if settings.email else ""
    while True:
        value = input(f"Votre adresse email{current} (Entrée pour garder ou passer) : ").strip()
        if not value or config.valid_email(value):
            break
        print("Adresse invalide, recommencez.")
    if value:
        settings.email = value
        log.info("réglages enregistrés dans %s", config.save(args.db, settings))


def cmd_setup(args: argparse.Namespace) -> None:
    conn = _connect(args)
    seed_arg = getattr(args, "seed", None)
    seed = Path(seed_arg) if seed_arg else DEFAULT_SEED
    if seed.exists():
        loaded = db.load_seed(conn, seed)
        actives = sum(1 for _, e in loaded if e.get("enabled", 1))
        log.info("%d revue(s) chargée(s) depuis %s, dont %d active(s)",
                 len(loaded), seed.name, actives)
    else:
        log.warning("fichier de revues introuvable : %s", seed)
    if getattr(args, "openalex_key", None):
        config.get().openalex_api_key = args.openalex_key.strip()
    if args.email or getattr(args, "openalex_key", None):
        log.info("réglages enregistrés dans %s", config.save(args.db, config.get()))
    _ask_email(args)
    if not config.get().email:
        log.warning("aucun email enregistré : la veille fonctionne, mais plus lentement "
                    "chez Crossref. Ajoutez-le plus tard (menu, choix 5).")
    log.info("base prête : %s", Path(args.db).resolve())
    log.info("étape suivante : python -m veille routine (premier passage : 1 à 2 heures)")


# --- Moissonnage -----------------------------------------------------------

def cmd_update(args: argparse.Namespace) -> Optional[Path]:
    conn = _connect(args)
    if db.count_sources(conn) == 0:
        log.error("aucune revue en base : lancez d'abord  python -m veille setup")
        return None
    global_start = db.now_utc()
    total_new = total_upd = 0
    failures: list[str] = []
    wanted = set(args.source or [])

    for source in db.get_enabled_sources(conn):
        if wanted and source["id"] not in wanted:
            continue
        connector_cls = CONNECTORS.get(source["connector"])
        if connector_cls is None:
            log.info("#%d %s : connecteur '%s' inconnu, revue ignorée",
                     source["id"], source["name"], source["connector"])
            continue
        log.info("#%d %s ...", source["id"], source["name"])
        run_id = db.start_run(conn, source["id"])
        source_start = db.now_utc()
        since = _parse_since(source["last_run"])
        n_new = n_upd = 0
        try:
            if source["connector"] in ("metadata", "scraper"):
                connector = connector_cls(enrich_abstracts=not args.no_enrich)
            else:
                connector = connector_cls()
            for rec in connector.fetch_new(source, since):
                if rec.deleted or not rec.title:
                    continue
                work_id, status = db.upsert_work(conn, rec)
                if status == "new":
                    n_new += 1
                else:
                    n_upd += 1
                if rec.full_text_url:
                    db.add_file(conn, work_id, kind=FileKind.PUBLISHER, url=rec.full_text_url)
                if rec.oa_url:
                    db.add_file(conn, work_id, kind=FileKind.OA, url=rec.oa_url)
            db.set_last_run(conn, source["id"], source_start)
            db.finish_run(conn, run_id, n_new=n_new, n_updated=n_upd)
            log.info("#%d %s : %d nouvelle(s), %d mise(s) à jour",
                     source["id"], source["name"], n_new, n_upd)
        except Exception as exc:  # une revue en echec ne bloque pas les autres
            db.finish_run(conn, run_id, n_new=n_new, n_updated=n_upd,
                          status="error", message=str(exc))
            log.warning("#%d %s : échec (%s). Elle sera reprise au prochain passage.",
                        source["id"], source["name"], exc)
            failures.append(source["name"])
        total_new += n_new
        total_upd += n_upd

    log.info("moisson terminée : %d nouvelle(s) notice(s), %d mise(s) à jour",
             total_new, total_upd)
    if failures:
        log.warning("revue(s) en échec : %s", ", ".join(failures))
    if args.digest is not None:
        path = Path(args.digest) if args.digest else _auto_digest_path(args)
        _write_digest(conn, global_start, path)
        return path
    return None


def _auto_digest_path(args: argparse.Namespace) -> Path:
    folder = _data_dir(args) / "digests"
    base = folder / f"{date.today().isoformat()}.md"
    path, n = base, 1
    while path.exists():
        n += 1
        path = folder / f"{date.today().isoformat()}-{n}.md"
    return path


def _write_digest(conn: sqlite3.Connection, since_iso: str, path: Path) -> None:
    rows = list(db.new_works_since(conn, since_iso))
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Veille du {since_iso[:10]}", "",
             f"{len(rows)} nouvelle(s) publication(s).", ""]
    current = object()
    for r in rows:
        if r["journal"] != current:
            current = r["journal"]
            lines += [f"## {current or 'Revue inconnue'}", ""]
        authors = "; ".join(json.loads(r["authors_json"])) or "auteur inconnu"
        meta = authors + (f" ({r['year']})" if r["year"] else "")
        lines += [f"### {r['title']}", "", meta]
        if r["doi"]:
            lines.append(f"<https://doi.org/{r['doi']}>")
        if r["abstract"]:
            lines += ["", r["abstract"]]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("nouveautés écrites dans %s (%d notice(s))", path, len(rows))


# --- Enrichissement --------------------------------------------------------

def cmd_resolve(args: argparse.Namespace) -> None:
    from .resolve import resolve_pdf_urls
    conn = _connect(args)
    seen, found = resolve_pdf_urls(
        conn, limit=args.limit, page_pause=args.pause,
        require_doi=not args.with_titles, min_year=args.min_year or None,
        recheck_days=args.recheck,
    )
    log.info("liens PDF : %d trouvé(s) sur %d notice(s) examinée(s)", found, seen)


def cmd_references(args: argparse.Namespace) -> None:
    from .references import backfill_references
    conn = _connect(args)
    seen, filled = backfill_references(conn, limit=args.limit, page_pause=args.pause,
                                       min_year=args.min_year, recheck_days=args.recheck)
    log.info("références : %d bibliographie(s) complétée(s) sur %d notice(s) examinée(s)",
             filled, seen)


def cmd_download(args: argparse.Namespace) -> None:
    from .download import download_pdfs
    conn = _connect(args)
    out = Path(args.out) if args.out else _data_dir(args) / "pdfs"
    seen, ok = download_pdfs(conn, out, min_year=args.min_year,
                             limit=args.limit, page_pause=args.pause)
    log.info("téléchargement (année >= %d) : %d PDF sur %d éligible(s), dans %s",
             args.min_year, ok, seen, out)


def cmd_export(args: argparse.Namespace) -> None:
    from .export import export
    if not args.bib and not args.urls:
        log.error("préciser au moins --bib FICHIER ou --urls FICHIER")
        return
    conn = _connect(args)
    n, n_urls = export(conn, bib_path=args.bib, urls_path=args.urls,
                       min_year=args.min_year, journal=args.journal,
                       source_id=args.source_id, new_since=args.new_since,
                       with_pdf=args.with_pdf)
    if args.bib:
        log.info("BibTeX : %d notice(s) dans %s", n, args.bib)
    if args.urls:
        log.info("liens PDF : %d lien(s) dans %s", n_urls, args.urls)


def cmd_routine(args: argparse.Namespace) -> None:
    """Le passage complet, a relancer aussi souvent qu'on veut."""
    from .export import export
    from .references import backfill_references
    from .resolve import resolve_pdf_urls

    args.digest = ""          # chemin automatique
    args.source = None
    log.info("1/4 moisson des revues")
    digest = cmd_update(args)
    conn = _connect(args)
    if db.count_sources(conn) == 0:
        return
    log.info("2/4 recherche de liens PDF en accès ouvert")
    seen, found = resolve_pdf_urls(conn)
    log.info("liens PDF : %d trouvé(s) sur %d notice(s) examinée(s)", found, seen)
    log.info("3/4 complétion des bibliographies")
    seen, filled = backfill_references(conn)
    log.info("références : %d complétée(s) sur %d examinée(s)", filled, seen)
    log.info("4/4 exports")
    exports = _data_dir(args) / "exports"
    n, _ = export(conn, bib_path=str(exports / "veille.bib"))
    recent = date.today().year - 1
    _, n_urls = export(conn, urls_path=str(exports / "liens-pdf-recents.txt"),
                       min_year=recent, with_pdf=True)
    log.info("BibTeX complet : %s (%d notices)", exports / "veille.bib", n)
    log.info("liens PDF depuis %d : %s (%d liens)", recent,
             exports / "liens-pdf-recents.txt", n_urls)
    if digest:
        log.info("nouveautés du jour : %s", digest)


# --- Consultation ----------------------------------------------------------

def cmd_sources(args: argparse.Namespace) -> None:
    conn = _connect(args)
    rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    if not rows:
        print("(aucune revue ; lancez  python -m veille setup)")
        return
    for r in rows:
        flag = "active  " if r["enabled"] else "inactive"
        last = (r["last_run"] or "jamais")[:16].replace("T", " ")
        print(f"#{r['id']:>2} [{flag}] {r['connector']:<8} {r['name']}  (dernier passage : {last})")


def cmd_stats(args: argparse.Namespace) -> None:
    conn = _connect(args)
    rows = db.stats(conn)
    if not rows:
        print("(aucune revue ; lancez  python -m veille setup)")
        return
    print(f"{'#':>3}  {'revue':<48} {'notices':>8} {'PDF':>6} {'refs':>6}  dernier passage")
    tot = [0, 0, 0]
    for r in rows:
        last = (r["last_run"] or "jamais")[:10]
        name = r["name"] if len(r["name"]) <= 48 else r["name"][:45] + "..."
        flag = "" if r["enabled"] else " (inactive)"
        print(f"{r['id']:>3}  {name:<48} {r['n_works'] or 0:>8} {r['n_pdf'] or 0:>6} "
              f"{r['n_refs'] or 0:>6}  {last}{flag}")
        tot = [tot[0] + (r["n_works"] or 0), tot[1] + (r["n_pdf"] or 0), tot[2] + (r["n_refs"] or 0)]
    print(f"{'':>3}  {'TOTAL':<48} {tot[0]:>8} {tot[1]:>6} {tot[2]:>6}")


def cmd_discover(args: argparse.Namespace) -> None:
    oai = OaiConnector()
    info = oai.identify(args.base_url)
    print("== Identify ==")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print("\n== ListSets ==")
    sets = oai.list_sets(args.base_url)
    if not sets:
        print("  (aucun set : l'entrepôt expose peut-être une seule revue)")
    for spec, name in sets:
        print(f"  {spec:<30} {name}")


def cmd_check(args: argparse.Namespace) -> None:
    """Verifie que Crossref connait bien les ISSN des revues `metadata`."""
    from .connectors.metadata import CROSSREF_URL
    conn = _connect(args)
    rows = conn.execute("SELECT * FROM sources WHERE connector = 'metadata' ORDER BY id").fetchall()
    email = config.get().email
    for r in rows:
        if args.source_id and r["id"] != args.source_id:
            continue
        issns = [i for i in (r["issn_print"], r["issn_online"]) if i]
        if not issns:
            print(f"#{r['id']:>2} {r['name']} : aucun ISSN")
            continue
        params = {"filter": ",".join(f"issn:{i}" for i in issns), "rows": "0"}
        if email:
            params["mailto"] = email
        try:
            data = http.fetch(CROSSREF_URL, params)
            total = (data.get("message") or {}).get("total-results", 0)
            verdict = "ok" if total else "AUCUN RÉSULTAT : ISSN à revoir"
            print(f"#{r['id']:>2} {r['name']} : {total} notice(s) chez Crossref ({verdict})")
        except Exception as exc:
            print(f"#{r['id']:>2} {r['name']} : échec ({exc})")


# --- Menu interactif -------------------------------------------------------

def _open(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        print(f"Ouvrez vous-même : {path}")


def cmd_menu(args: argparse.Namespace) -> None:
    data = _data_dir(args)
    if not Path(args.db).exists():
        print("Première utilisation : installation de la base et des revues.\n")
        cmd_setup(args)
        print()
    while True:
        conn = _connect(args)
        n_works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        n_src = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled = 1").fetchone()[0]
        conn.close()
        email = config.get().email or "non renseigné"
        print(f"\n=== Veille scientifique {__version__} ===")
        print(f"{n_src} revues actives, {n_works} notices en base. Contact : {email}")
        print("  1  Mettre à jour la veille (moisson, liens PDF, références, exports)")
        print("  2  Lire les nouveautés du dernier passage")
        print("  3  Ouvrir le dossier des exports (BibTeX pour JabRef, liens PDF)")
        print("  4  Bilan par revue")
        print("  5  Régler mon adresse email")
        print("  0  Quitter")
        choice = input("Votre choix : ").strip()
        if choice == "1":
            print("\nMise à jour en cours. La première fois, comptez une à deux heures ;")
            print("ensuite quelques minutes. Vous pouvez interrompre avec Ctrl+C :")
            print("rien n'est perdu, le travail reprendra au prochain lancement.\n")
            try:
                cmd_routine(args)
            except KeyboardInterrupt:
                print("\nInterrompu. Relancez la mise à jour quand vous voulez.")
        elif choice == "2":
            digests = sorted((data / "digests").glob("*.md"), key=lambda p: p.stat().st_mtime)
            if digests:
                _open(digests[-1])
            else:
                print("Aucune nouveauté enregistrée : lancez d'abord une mise à jour.")
        elif choice == "3":
            (data / "exports").mkdir(parents=True, exist_ok=True)
            _open(data / "exports")
        elif choice == "4":
            print()
            cmd_stats(args)
        elif choice == "5":
            _ask_email(args, force=True)
        elif choice in ("0", "q", "Q", ""):
            return
        else:
            print("Choix non reconnu.")


# --- Analyse des arguments -------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="veille",
                                description="Veille scientifique par moissonnage de revues")
    p.add_argument("--db", default=str(DEFAULT_DB),
                   help=f"chemin de la base (defaut : {DEFAULT_DB})")
    p.add_argument("--email", help="adresse de contact pour Crossref et OpenAlex")
    p.add_argument("-v", "--verbose", action="store_true", help="affiche chaque requete")
    p.add_argument("--version", action="version", version=f"veille {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="commande")

    ps = sub.add_parser("setup", help="installation : base, revues, email")
    ps.add_argument("--seed", help="fichier de revues (defaut : sources.seed.json)")
    ps.add_argument("--no-prompt", action="store_true", help="ne pose aucune question")
    ps.add_argument("--email", default=argparse.SUPPRESS, help="adresse de contact a enregistrer")
    ps.add_argument("--openalex-key", dest="openalex_key", metavar="CLE",
                    help="cle OpenAlex gratuite (facultative, releve le quota quotidien)")
    ps.set_defaults(func=cmd_setup)

    pi = sub.add_parser("init", help="synonyme de setup, sans question")
    pi.add_argument("--seed")
    pi.set_defaults(func=cmd_setup, no_prompt=True)

    pr = sub.add_parser("routine", help="mise a jour complete en une commande")
    pr.add_argument("--no-enrich", action="store_true",
                    help="moisson rapide : sans resumes OpenAlex ni detail des articles IREM")
    pr.set_defaults(func=cmd_routine)

    pm = sub.add_parser("menu", help="menu interactif")
    pm.add_argument("--no-enrich", action="store_true", help=argparse.SUPPRESS)
    pm.set_defaults(func=cmd_menu)

    pu = sub.add_parser("update", help="moissonne les revues actives")
    pu.add_argument("--digest", nargs="?", const="", default=None,
                    help="ecrit les nouveautes en Markdown (chemin optionnel ; "
                         "defaut : donnees/digests/AAAA-MM-JJ.md)")
    pu.add_argument("--no-enrich", action="store_true",
                    help="plus rapide : sans resumes OpenAlex ni detail des articles IREM")
    pu.add_argument("--source", type=int, action="append",
                    help="ne moissonner que cette revue (numero ; option repetable)")
    pu.set_defaults(func=cmd_update)

    pre = sub.add_parser("resolve", help="cherche des liens de PDF en acces ouvert")
    pre.add_argument("--limit", type=int, help="ne traiter que N notices (essai)")
    pre.add_argument("--pause", type=float, default=0.34, help="pause entre requetes (s)")
    pre.add_argument("--min-year", type=int, default=2000, dest="min_year",
                     help="ignorer les notices plus anciennes (defaut : 2000 ; 0 = toutes)")
    pre.add_argument("--recheck", type=int, default=180, metavar="JOURS",
                     help="reexaminer les notices sans PDF apres JOURS jours (defaut : 180)")
    pre.add_argument("--with-titles", action="store_true", dest="with_titles",
                     help="chercher aussi par titre les notices sans DOI (lent, peu fructueux)")
    pre.add_argument("--require-doi", action="store_true", help=argparse.SUPPRESS)
    pre.set_defaults(func=cmd_resolve)

    pref = sub.add_parser("references", help="complete les bibliographies via Crossref")
    pref.add_argument("--limit", type=int, help="ne traiter que N notices (essai)")
    pref.add_argument("--pause", type=float, default=0.34, help="pause entre requetes (s)")
    pref.add_argument("--min-year", type=int, dest="min_year", help="annee minimale")
    pref.add_argument("--recheck", type=int, metavar="JOURS",
                      help="reexaminer les notices sans references apres JOURS jours")
    pref.set_defaults(func=cmd_references)

    pe = sub.add_parser("export", help="exporte en BibTeX et/ou en liste de liens PDF")
    pe.add_argument("--bib", help="fichier BibTeX a ecrire")
    pe.add_argument("--urls", help="fichier de liens PDF a ecrire (un par ligne)")
    pe.add_argument("--min-year", type=int, dest="min_year", help="annee minimale")
    pe.add_argument("--journal", help="nom exact d'une revue")
    pe.add_argument("--source-id", type=int, dest="source_id", help="numero de revue")
    pe.add_argument("--new-since", dest="new_since", metavar="AAAA-MM-JJ",
                    help="notices apparues depuis cette date")
    pe.add_argument("--with-pdf", action="store_true", dest="with_pdf",
                    help="seulement les notices ayant un lien PDF libre")
    pe.set_defaults(func=cmd_export)

    pd = sub.add_parser("download", help="telecharge des PDF recents (usage ponctuel)")
    pd.add_argument("--out", help="dossier de destination (defaut : donnees/pdfs)")
    pd.add_argument("--min-year", type=int, default=date.today().year, dest="min_year",
                    help="annee minimale (defaut : annee en cours)")
    pd.add_argument("--limit", type=int, help="nombre maximal de PDF")
    pd.add_argument("--pause", type=float, default=1.0, help="pause entre telechargements (s)")
    pd.set_defaults(func=cmd_download)

    sub.add_parser("sources", help="liste les revues").set_defaults(func=cmd_sources)
    sub.add_parser("stats", help="bilan par revue").set_defaults(func=cmd_stats)

    pc = sub.add_parser("check", help="verifie les ISSN des revues `metadata` chez Crossref")
    pc.add_argument("--source-id", type=int, dest="source_id", help="une seule revue")
    pc.set_defaults(func=cmd_check)

    pdi = sub.add_parser("discover", help="explore un entrepot OAI-PMH")
    pdi.add_argument("base_url", help="URL de base de l'entrepot OAI")
    pdi.set_defaults(func=cmd_discover)
    return p


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if record.levelno >= logging.ERROR:
            return f"ERREUR : {msg}"
        if record.levelno >= logging.WARNING:
            return f"ATTENTION : {msg}"
        return msg


def _setup_logging(verbose: bool) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_Formatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # httpx annonce chaque requete : utile pour deboguer, illisible sinon.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.INFO if verbose else logging.WARNING)


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd is None:  # sans commande : le menu
        args = build_parser().parse_args([*(argv or sys.argv[1:]), "menu"])
    _setup_logging(args.verbose)
    config.load(args.db, cli_email=args.email)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrompu. Rien n'est perdu : relancez quand vous voulez.")
        sys.exit(130)


if __name__ == "__main__":
    main()
