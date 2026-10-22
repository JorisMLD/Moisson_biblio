"""Reglages personnels : adresse email de contact et cle OpenAlex optionnelle.

Ces reglages ne doivent jamais etre versionnes (chaque utilisateur a les siens).
Ils vivent dans `config.json`, a cote de la base, fichier ignore par git.

Ordre de priorite, du plus fort au plus faible :
  1. option `--email` de la ligne de commande ;
  2. variables d'environnement VEILLE_EMAIL et OPENALEX_API_KEY ;
  3. fichier config.json.

L'email n'est pas obligatoire, mais Crossref et OpenAlex demandent de
s'identifier : avec une adresse, les requetes passent dans leur file
« polie », plus rapide et plus fiable. La cle OpenAlex est gratuite (compte sur
openalex.org) et releve le quota quotidien ; sans elle l'outil fonctionne.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

CONFIG_NAME = "config.json"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Settings:
    email: Optional[str] = None
    openalex_api_key: Optional[str] = None


_current = Settings()


def config_path(db_path: str | Path) -> Path:
    """Le fichier de reglages se trouve dans le meme dossier que la base."""
    return Path(db_path).resolve().parent / CONFIG_NAME


def load(db_path: str | Path, cli_email: Optional[str] = None) -> Settings:
    """Charge les reglages et les rend disponibles via `get()`."""
    global _current
    data: dict = {}
    path = config_path(db_path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            data = {}
    s = Settings(
        email=data.get("email") or None,
        openalex_api_key=data.get("openalex_api_key") or None,
    )
    if os.environ.get("VEILLE_EMAIL"):
        s.email = os.environ["VEILLE_EMAIL"].strip()
    if os.environ.get("OPENALEX_API_KEY"):
        s.openalex_api_key = os.environ["OPENALEX_API_KEY"].strip()
    if cli_email:
        s.email = cli_email.strip()
    _current = s
    return s


def save(db_path: str | Path, settings: Settings) -> Path:
    path = config_path(db_path)
    path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def get() -> Settings:
    return _current


def set_current(settings: Settings) -> None:
    """Utilise par les tests pour fixer des reglages sans fichier."""
    global _current
    _current = settings


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value.strip()))
