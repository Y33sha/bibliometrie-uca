"""Modèles Pydantic des colonnes JSONB de `source_publications` et `publications` : `external_ids`, `biblio`, `meta`, `topics`.

Validation à la construction (via les VO domain pour les identifiants), sérialisation en dict pour l'écriture en base.
"""

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from application.ports.api.publications_queries import EcoleDoctorale, PartenaireThese
from domain.publications.identifiers import DOI, NNT, PMCID, PMID, ArxivId, HALId
from infrastructure.jsonb_models._base import JsonbModel

# Types re-exportés (importables depuis ce module).
__all__ = [
    "EcoleDoctorale",
    "ExternalIds",
    "OpenAlexTopic",
    "PartenaireThese",
    "PublicationBiblio",
    "PublicationMeta",
    "PublicationTopics",
    "ThesesTopics",
]

# ── ExternalIds : colonne source_publications.external_ids ─────────


class _IdentifierVO(Protocol):
    """Contrat des value objects d'identifiant : attribut `.value` canonique."""

    @property
    def value(self) -> str: ...


# Champ → (`try_parse` du value object, libellé d'erreur).
_SCALAR_IDS: dict[str, tuple[Callable[[str | None], _IdentifierVO | None], str]] = {
    "nnt": (NNT.try_parse, "NNT"),
    "pmid": (PMID.try_parse, "PMID"),
    "pmcid": (PMCID.try_parse, "PMCID"),
    "arxiv_id": (ArxivId.try_parse, "arXiv ID"),
}
_LIST_IDS: dict[str, tuple[Callable[[str | None], _IdentifierVO | None], str]] = {
    "hal_id": (HALId.try_parse, "HAL ID"),
    "related_dois": (DOI.try_parse, "DOI"),
}


class ExternalIds(JsonbModel):
    """Modèle de la colonne JSONB `external_ids` des source_publications.

    Identifiants externes cross-source, utilisés notamment pour la déduplication (fusion par HAL-ID, par NNT, …). Les valeurs sont normalisées via les value objects du domaine — un HAL URL en entrée est stocké comme HAL ID canonique, un NNT est mis en majuscules, etc.

    `extra="allow"` autorise les clés non déclarées. Seules les clés déclarées ici sont validées/normalisées.
    """

    model_config = ConfigDict(extra="allow")

    hal_id: list[str] | None = None  # dépôts HAL référencés (ex. ["hal-04123456"])
    nnt: str | None = None  # Numéro National de Thèse
    pmid: str | None = None  # PubMed ID
    pmcid: str | None = None  # PubMed Central ID
    arxiv_id: str | None = None  # arXiv ID
    # Autres DOI du record (preprint, dépôt, dataset, édition, DOI de l'ouvrage hôte d'un chapitre), pour relations-publications.
    # Jamais clé de fusion : le DOI primaire de la publication est sur la colonne `doi`.
    related_dois: list[str] | None = None

    @field_validator("nnt", "pmid", "pmcid", "arxiv_id", mode="before")
    @classmethod
    def _normalize_scalar_id(cls, v: str | None, info: ValidationInfo) -> str | None:
        """Normalise un identifiant scalaire via son value object. Vide → None, invalide → `ValueError`."""
        if not v:
            return None
        assert info.field_name is not None
        parse, label = _SCALAR_IDS[info.field_name]
        parsed = parse(v)
        if parsed is None:
            raise ValueError(f"{label} invalide : {v!r}")
        return parsed.value

    @field_validator("hal_id", "related_dois", mode="before")
    @classmethod
    def _normalize_id_list(
        cls, v: str | list[str] | None, info: ValidationInfo
    ) -> list[str] | None:
        """Normalise et dédoublonne une liste d'identifiants via leur value object. Tolère un scalaire. Vide → None."""
        if not v:
            return None
        assert info.field_name is not None
        parse, label = _LIST_IDS[info.field_name]
        raw = [v] if isinstance(v, str) else list(v)
        out: list[str] = []
        for item in raw:
            parsed = parse(item)
            if parsed is None:
                raise ValueError(f"{label} invalide : {item!r}")
            if parsed.value not in out:
                out.append(parsed.value)
        return out or None


# ── PublicationBiblio : colonne biblio ─────────────────────────────


class PublicationBiblio(JsonbModel):
    """Modèle de la colonne JSONB `biblio` (sur source_publications ET publications).

    Contient les infos bibliographiques d'un article (volume, issue, numéro de page). **Schéma hétérogène selon la source** :
    - HAL → `pages` (range ex. "123-456", parfois avec préfixe genre "S123-S145" pour supplément)
    - OpenAlex, WoS → `first_page` + `last_page` (décomposé)

    Les deux formes peuvent coexister dans la même ligne après fusion (le merge shallow de refresh_from_sources ne dédoublonne pas). Tous les champs sont optionnels : toutes les clés rencontrées sont acceptées.
    """

    model_config = ConfigDict(extra="allow")

    volume: str | None = None
    issue: str | None = None
    pages: str | None = None  # HAL : range "123-456"
    first_page: str | None = None  # OpenAlex, WoS
    last_page: str | None = None  # OpenAlex, WoS


# ── PublicationMeta : colonne meta ─────────────────────────────────


class PublicationMeta(JsonbModel):
    """Modèle de la colonne JSONB `meta` (sur source_publications ET
    publications).

    Peuplée uniquement par theses.fr (champs thèse : dates de soutenance/inscription, discipline, écoles doctorales, partenaires). Le modèle reste ouvert (`extra="allow"`).

    `discipline` est la source de vérité pour la discipline d'une thèse ; `topics.theses.discipline` en contient une copie redondante.
    """

    model_config = ConfigDict(extra="allow")

    # Dates au format ISO 8601 (YYYY-MM-DD), stockées en string dans le JSONB.
    date_soutenance: str | None = None
    date_inscription: str | None = None

    discipline: str | None = None
    etablissement: str | None = None  # établissement de soutenance (theses.fr)
    ecoles_doctorales: list[EcoleDoctorale] | None = None
    partenaires: list[PartenaireThese] | None = None


# ── PublicationTopics : colonne topics ─────────────────────────────


class OpenAlexTopic(BaseModel):
    """Un élément de la hiérarchie thématique OpenAlex.

    Un document porte une liste de OpenAlexTopic : OpenAlex classe souvent en plusieurs sujets avec des scores. Tous les champs sont optionnels (données réelles parfois incomplètes).
    """

    model_config = ConfigDict(extra="allow")

    domain: str | None = None
    field: str | None = None
    subfield: str | None = None
    topic: str | None = None
    score: float | None = None


class ThesesTopics(BaseModel):
    """Topics au format theses.fr : discipline + termes Rameau.

    `discipline` est une copie redondante de `meta.discipline` (voir PublicationMeta).
    """

    model_config = ConfigDict(extra="allow")

    discipline: str | None = None
    rameau: list[str] | None = None


class PublicationTopics(JsonbModel):
    """Modèle de la colonne JSONB `topics` (sur publications,
    reconstituée par refresh_from_sources).

    **Container composite par source** — chaque source garde sa forme native, rien n'est perdu :
    - openalex : liste de OpenAlexTopic (hiérarchie thématique)
    - theses   : dict discipline+rameau
    - scanr    : dict non contrôlé (structure variable)

    Sur `source_publications.topics`, chaque ligne contient UNE seule forme (la forme native de la source). Sur `publications.topics`, le dict indexé par source est reconstitué à partir des sources.
    """

    model_config = ConfigDict(extra="allow")

    openalex: list[OpenAlexTopic] | None = None
    theses: ThesesTopics | None = None
    # ScanR a un format variable côté API, non figé en sous-modèle Pydantic.
    scanr: dict[str, Any] | None = None
