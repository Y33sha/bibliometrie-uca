"""Champs propres à une source, qu'aucune colonne commune de `source_records` ne reçoit.

`source_records.source_extras` les reçoit, `publications.source_extras` les fusionne par clé. Les normaliseurs qui les écrivent et le code qui les lit nomment les clés par `SourceExtra`. Un fait lu dans ces champs à la fois en SQL et en Python a son accesseur ici et son fragment dans `infrastructure/sql_fragments.py`.
"""

from collections.abc import Mapping
from enum import StrEnum

from domain.types import JsonValue


class SourceExtra(StrEnum):
    """Clé de `source_extras`."""

    LICENSE = "license"
    """Licence brute (Crossref, OpenAlex, ScanR)."""
    FUNDER = "funder"
    """Financeurs déclarés (Crossref)."""
    RELATION = "relation"
    """Relations déclarées, par type de relation (Crossref)."""
    CONFERENCE = "conference"
    """Nom et acronyme du congrès dont l'enregistrement source est issu (Crossref)."""
    GROUP_TITLE = "group_title"
    """Forme de présentation d'un `posted-content` (Crossref : `oral`, `pico`, `display`)."""
    REFERENCES_COUNT = "references_count"
    """Nombre de références (Crossref)."""
    INDEXED = "indexed"
    """Date d'indexation (Crossref)."""
    PROCEEDINGS = "proceedings"
    """Indicateur « avec actes » (HAL)."""
    SERIES = "series"
    """Collections (HAL)."""
    SOURCE_TITLE = "source_title"
    """Titre de la source (HAL)."""
    LICENCE = "licence"
    """Licence du dépôt (HAL)."""
    ANNEX_DEPOSIT = "annex_deposit"
    """Dépôt réduit à des annexes, sans fichier principal (HAL)."""
    RELATED_IDENTIFIERS = "related_identifiers"
    """Identifiants liés, avec leur type de relation (DataCite)."""
    RIGHTS = "rights"
    """Droits (DataCite)."""
    FUNDING = "funding"
    """Financements (DataCite)."""
    DATE_SOUTENANCE = "date_soutenance"
    """Date de soutenance (theses.fr)."""
    DATE_INSCRIPTION = "date_inscription"
    """Date d'inscription (theses.fr)."""
    ETABLISSEMENT = "etablissement"
    """Établissement de soutenance (theses.fr)."""
    ETABLISSEMENT_PPN = "etablissement_ppn"
    """PPN de l'établissement de soutenance (theses.fr)."""
    ECOLES_DOCTORALES = "ecoles_doctorales"
    """Écoles doctorales (theses.fr)."""
    PARTENAIRES = "partenaires"
    """Partenaires de recherche (theses.fr)."""
    INTRANET_ONLY = "intranet_only"
    """Thèse réservée à l'intranet de son établissement, cas de diffusion STAR 5 et 6 (theses.fr)."""


CROSSREF_PREPRINT_OF = "is-preprint-of"
"""Type de relation Crossref d'un enregistrement source qui est le preprint d'une autre œuvre."""


def declares_conference(source_extras: Mapping[str, JsonValue] | None) -> bool:
    """Vrai si l'enregistrement source nomme le congrès dont il est issu."""
    return SourceExtra.CONFERENCE in (source_extras or {})
