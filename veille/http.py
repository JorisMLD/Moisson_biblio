"""Couche HTTP unique pour tout l'outil.

Toutes les requetes passent par `fetch`, qui applique la meme politique :
  - erreurs reseau et erreurs serveur (5xx) : nouvel essai avec attente croissante ;
  - 429 (trop de requetes) : on respecte l'en-tete Retry-After, borne ;
  - autres 4xx (requete invalide, page absente) : echec immediat, inutile d'insister.

Deux identites : les API (Crossref, OpenAlex, HAL, OAI) recoivent un
User-Agent qui nomme l'outil et l'email de contact, comme elles le demandent ;
les sites de revues et les telechargements recoivent un User-Agent de
navigateur, sans lequel certains sites repondent mal.

Un client par identite est conserve pour reutiliser les connexions.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from . import __version__, config

log = logging.getLogger("veille")

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/124.0 Safari/537.36 veille-scientifique/{__version__}"
)

_clients: dict[str, Any] = {}


class HttpError(RuntimeError):
    """Echec definitif d'une requete. `status` vaut le code HTTP, ou None si
    l'echec est reseau (pas de reponse)."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def api_user_agent() -> str:
    email = config.get().email
    contact = f"; mailto:{email}" if email else ""
    return f"veille-scientifique/{__version__} (outil de veille bibliographique{contact})"


def _client(browser: bool):
    import httpx

    ua = BROWSER_UA if browser else api_user_agent()
    key = ua
    client = _clients.get(key)
    if client is None:
        client = httpx.Client(timeout=30.0, follow_redirects=True,
                              headers={"User-Agent": ua})
        _clients[key] = client
    return client


def fetch(
    url: str,
    params: Optional[dict] = None,
    *,
    as_: str = "json",
    browser: bool = False,
    attempts: int = 5,
    max_wait: float = 120.0,
) -> Any:
    """Effectue un GET et renvoie le JSON decode, le texte ou les octets.

    `as_` vaut "json", "text" ou "bytes". Leve HttpError en cas d'echec definitif.
    """
    import httpx

    last: Optional[Exception] = None
    last_status: Optional[int] = None
    for attempt in range(1, attempts + 1):
        try:
            resp = _client(browser).get(url, params=params)
            resp.raise_for_status()
            if as_ == "json":
                return resp.json()
            if as_ == "bytes":
                return resp.content
            return resp.text
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            last, last_status = exc, code
            if code == 429:
                ra = exc.response.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra is not None else 30.0
                except ValueError:
                    wait = 30.0
                wait = min(max(wait, 5.0), max_wait)
                log.warning("serveur saturé (429) sur %s : pause de %.0f s (essai %d/%d)",
                            _host(url), wait, attempt, attempts)
                time.sleep(wait)
                continue
            if 400 <= code < 500:
                raise HttpError(f"HTTP {code} sur {_short(url)}", code) from exc
            time.sleep(min(2.0 * attempt, 10.0))
        except (httpx.TransportError, ValueError) as exc:
            last, last_status = exc, None
            time.sleep(min(2.0 * attempt, 10.0))
    raise HttpError(f"échec après {attempts} essais sur {_short(url)}", last_status) from last


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(url).netloc or url


def _short(url: str) -> str:
    return url if len(url) <= 100 else url[:97] + "..."
