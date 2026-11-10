"""Champs propres à une source, qu'aucune colonne commune de `source_records` ne reçoit.

`source_records.source_extras` les reçoit, `publications.source_extras` les fusionne par clé. Les normaliseurs qui les écrivent et le code qui les lit nomment les clés par `SourceExtra`. Un fait lu dans ces champs à la fois en SQL et en Python a son accesseur ici et son fragment dans `infrastructure/sql_fragments.py`.
"""

from collections.abc import Mapping
from enum import StrEnum

from domain.types import JsonValue


class SourceExtra(StrEnum):
    """Clé de `source_extras`."""

    FUNDER = "funder"
    """Financeurs déclarés (Crossref)."""
    RELATION = "relation"
    """Relations déclarées, par type de relation (Crossref)."""
    CONFERENCE = "conference"
    """Nom et acronyme du congrès de l'enregistrement source (Crossref)."""
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
    PATENT_APPLICATIONS = "patent_applications"
    """Demandes de la famille de brevets, avec leurs numéros et leurs dates (OPS)."""
    PATENT_APPLICANTS = "patent_applicants"
    """Noms des déposants de la famille de brevets, un par déposant (OPS)."""
    PATENT_APPLICANT_FORMS = "patent_applicant_forms"
    """Formes de comparaison des noms des déposants, tous formats confondus, comparées aux graphies de `structures.api_ids.ops` (OPS)."""
    PATENT_FIRST_PUBLICATION_DATE = "patent_first_publication_date"
    """Date de la première publication d'une demande de la famille (OPS)."""
    PATENT_GRANT_DATE = "patent_grant_date"
    """Date de la première délivrance d'un brevet de la famille (OPS)."""
    CPC = "cpc"
    """Codes de la classification coopérative des brevets (CPC) (OPS)."""


CROSSREF_PREPRINT_OF = "is-preprint-of"
"""Type de relation Crossref d'un enregistrement source qui est le preprint d'une autre œuvre."""


def declares_conference(source_extras: Mapping[str, JsonValue] | None) -> bool:
    """Vrai si l'enregistrement source nomme son congrès."""
    return SourceExtra.CONFERENCE in (source_extras or {})
