"""Champs des thèses de theses.fr : identifiant, DOI, statut."""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_str


def extract_id(these: Mapping[str, JsonValue]) -> str:
    """Identifiant d'une thèse (champ `id`) : le NNT d'une thèse soutenue (`2021UCFAC022`), l'identifiant theses.fr d'une thèse en cours (`s367812`)."""
    return as_str(these.get("id")) or ""


def extract_doi(these: Mapping[str, JsonValue]) -> str | None:
    """DOI nettoyé d'une thèse (champ `doi`), ou `None`."""
    doi = these.get("doi")
    return clean_doi(doi) if isinstance(doi, str) else None


def is_ongoing(these: Mapping[str, JsonValue]) -> bool:
    """Vrai pour une thèse en cours, qui n'a ni soutenance ni NNT."""
    return as_str(these.get("status")) == "enCours"
