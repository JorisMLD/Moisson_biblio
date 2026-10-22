"""Interface commune a tous les connecteurs.

Chaque regime de moissonnage (API metadonnees, OAI-PMH, scraping) implemente
cette interface. L'orchestrateur ne manipule que des Connector et des
RawRecord, sans rien savoir de la mecanique propre a chaque source.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime

from ..models import RawRecord


class Connector(ABC):
    """Contrat minimal d'un connecteur de moissonnage."""

    #: identifiant court du connecteur, doit correspondre a sources.connector
    name: str = ""

    @abstractmethod
    def fetch_new(
        self, source: sqlite3.Row, since: datetime | None
    ) -> Iterator[RawRecord]:
        """Produit les notices nouvelles ou modifiees depuis `since`.

        `source` est une ligne de la table sources. `since` vaut None au premier
        passage (moissonnage complet). Le connecteur est responsable de la
        pagination et de l'incrementalite propres a sa source.
        """
        raise NotImplementedError
