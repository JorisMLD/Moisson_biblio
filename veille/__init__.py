"""Outil de veille scientifique : moissonnage périodique de revues.

Architecture : un registre de sources alimente des connecteurs interchangeables
(metadonnees, OAI-PMH, scrapers) qui produisent des notices normalisees,
dedupliquees puis stockees dans une base SQLite.
"""

__version__ = "1.0.0"
