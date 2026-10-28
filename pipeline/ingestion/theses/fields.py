"""Champs des thèses de theses.fr : identifiant, DOI, statut."""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_str


def listed_id(hit: Mapping[str, JsonValue]) -> str:
    """Identifiant d'une thèse dans une réponse de la recherche (champ `id`)."""
    return as_str(hit.get("id")) or ""


def extract_id(thesis: Mapping[str, JsonValue]) -> str:
    """Identifiant du détail d'une thèse : le NNT d'une thèse soutenue (`2021UCFAC022`), à défaut l'identifiant theses.fr d'une thèse en cours (`s367812`)."""
    return as_str(thesis.get("nnt")) or as_str(thesis.get("numSujet")) or ""


def extract_doi(thesis: Mapping[str, JsonValue]) -> str | None:
    """DOI nettoyé d'une thèse (champ `doi`), ou `None`."""
    doi = thesis.get("doi")
    return clean_doi(doi) if isinstance(doi, str) else None


def is_ongoing(thesis: Mapping[str, JsonValue]) -> bool:
    """Vrai pour une thèse en cours, qui n'a ni soutenance ni NNT."""
    return as_str(thesis.get("status")) == "enCours"
