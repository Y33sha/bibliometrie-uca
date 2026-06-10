"""Modèles Pydantic des colonnes JSONB de `source_publications` et
`publications` : `external_ids`, `biblio`, `meta`, `topics`.

Validation à la construction (en réutilisant les VO domain pour les
identifiants), sérialisation en dict pour l'écriture en base.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from application.ports.api.publications_queries import EcoleDoctorale, PartenaireThese
from domain.publications.identifiers import DOI, NNT, PMCID, PMID, ArxivId, HALId

# Re-export pour compat des tests / importeurs historiques.
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


class ExternalIds(BaseModel):
    """Modèle de la colonne JSONB `external_ids` des source_publications.

    Identifiants externes cross-source, utilisés notamment pour la
    déduplication (fusion par HAL-ID, par NNT, …). Les valeurs sont
    normalisées via les value objects du domaine — un HAL URL en entrée
    est stocké comme HAL ID canonique, un NNT est mis en majuscules, etc.

    `extra="allow"` autorise les clés non déclarées (issn, …)
    pour ne pas bloquer l'évolution du schéma sur une clé nouvelle.
    Les clés déclarées ici sont les seules qui sont validées/normalisées.
    """

    model_config = ConfigDict(extra="allow")

    hal_id: list[str] | None = None  # dépôts HAL référencés (ex. ["hal-04123456"])
    nnt: str | None = None  # Numéro National de Thèse
    pmid: str | None = None  # PubMed ID
    pmcid: str | None = None  # PubMed Central ID
    arxiv_id: str | None = None  # arXiv ID
    # Autres DOI présents dans le record (preprint, dépôt, dataset, édition,
    # DOI de l'ouvrage hôte d'un chapitre) — pour relations-publications. Jamais
    # clé de fusion : le DOI primaire de la publication est sur la colonne `doi`.
    related_dois: list[str] | None = None

    @field_validator("hal_id", mode="before")
    @classmethod
    def _normalize_hal_id(cls, v: str | list[str] | None) -> list[str] | None:
        """Normalise chaque hal_id via HALId (URL → ID canonique, strip version) ;
        dédoublonne. Tolère un scalaire (données pré-migration) en plus d'une liste."""
        if v is None or v == "":
            return None
        raw = [v] if isinstance(v, str) else list(v)
        out: list[str] = []
        for item in raw:
            normalized = HALId.try_parse(item)
            if normalized is None:
                raise ValueError(f"HAL ID invalide : {item!r}")
            if normalized.value not in out:
                out.append(normalized.value)
        return out or None

    @field_validator("nnt", mode="before")
    @classmethod
    def _normalize_nnt(cls, v: str | None) -> str | None:
        """Normalise via NNT : trim + uppercase."""
        if v is None or v == "":
            return None
        normalized = NNT.try_parse(v)
        if normalized is None:
            raise ValueError(f"NNT invalide : {v!r}")
        return normalized.value

    @field_validator("pmid", mode="before")
    @classmethod
    def _normalize_pmid(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        normalized = PMID.try_parse(v)
        if normalized is None:
            raise ValueError(f"PMID invalide : {v!r}")
        return normalized.value

    @field_validator("pmcid", mode="before")
    @classmethod
    def _normalize_pmcid(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        normalized = PMCID.try_parse(v)
        if normalized is None:
            raise ValueError(f"PMCID invalide : {v!r}")
        return normalized.value

    @field_validator("arxiv_id", mode="before")
    @classmethod
    def _normalize_arxiv_id(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        normalized = ArxivId.try_parse(v)
        if normalized is None:
            raise ValueError(f"arXiv ID invalide : {v!r}")
        return normalized.value

    @field_validator("related_dois", mode="before")
    @classmethod
    def _normalize_related_dois(cls, v: str | list[str] | None) -> list[str] | None:
        """Normalise chaque DOI via le VO DOI ; dédoublonne. Tolère un scalaire."""
        if v is None or v == "":
            return None
        raw = [v] if isinstance(v, str) else list(v)
        out: list[str] = []
        for item in raw:
            normalized = DOI.try_parse(item)
            if normalized is None:
                raise ValueError(f"DOI invalide : {item!r}")
            if normalized.value not in out:
                out.append(normalized.value)
        return out or None

    def to_dict(self) -> dict[str, Any]:
        """Sérialise pour écriture en base (JSONB).

        Omet les clés None pour garder des objets compacts côté BD.
        Préserve les clés supplémentaires (extra="allow"). `Any`
        justifié : sortie destinée à une colonne JSONB.
        """
        return self.model_dump(exclude_none=True)


# ── PublicationBiblio : colonne biblio ─────────────────────────────


class PublicationBiblio(BaseModel):
    """Modèle de la colonne JSONB `biblio` (sur source_publications ET
    publications).

    Contient les infos bibliographiques d'un article (volume, issue,
    numéro de page). **Schéma hétérogène selon la source** :
    - HAL → `pages` (range ex. "123-456", potentiellement avec préfixe
      genre "S123-S145" pour supplément)
    - OpenAlex, WoS → `first_page` + `last_page` (décomposé)

    Les deux peuvent coexister dans la même ligne après fusion (le
    merge shallow de refresh_from_sources ne dédoublonne pas). Les
    champs sont **tous optionnels** — on accepte toutes les clés
    rencontrées sans chercher à les unifier, tant qu'on n'a pas tranché.
    """

    model_config = ConfigDict(extra="allow")

    volume: str | None = None
    issue: str | None = None
    pages: str | None = None  # HAL : range "123-456"
    first_page: str | None = None  # OpenAlex, WoS
    last_page: str | None = None  # OpenAlex, WoS

    def to_dict(self) -> dict[str, Any]:
        """Sérialise pour écriture en base (colonne JSONB `biblio`). `Any`
        justifié : sortie destinée à une colonne JSONB."""
        return self.model_dump(exclude_none=True)


# ── PublicationMeta : colonne meta ─────────────────────────────────


class PublicationMeta(BaseModel):
    """Modèle de la colonne JSONB `meta` (sur source_publications ET
    publications).

    Aujourd'hui peuplée uniquement par theses.fr (champs thèse :
    dates de soutenance/inscription, discipline, écoles doctorales,
    partenaires). Le modèle reste ouvert (extra="allow") pour
    accueillir d'autres types de métadonnées plus tard sans migration.

    `discipline` est la source de vérité pour la discipline d'une
    thèse (par convention dans le projet) — `topics.theses.discipline`
    en contient aussi une copie historique qu'il faudra purger.
    """

    model_config = ConfigDict(extra="allow")

    # Dates au format ISO 8601 (YYYY-MM-DD) — stockées en string dans
    # le JSONB, pas de type date Pydantic pour simplifier la sérialisation.
    date_soutenance: str | None = None
    date_inscription: str | None = None

    discipline: str | None = None
    etablissement: str | None = None  # établissement de soutenance (theses.fr)
    ecoles_doctorales: list[EcoleDoctorale] | None = None
    partenaires: list[PartenaireThese] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Sérialise pour écriture en base (colonne JSONB `meta`). `Any`
        justifié : sortie destinée à une colonne JSONB."""
        return self.model_dump(exclude_none=True)


# ── PublicationTopics : colonne topics ─────────────────────────────


class OpenAlexTopic(BaseModel):
    """Un élément de la hiérarchie thématique OpenAlex.

    Un document a plusieurs lignes de ce type (une liste de OpenAlexTopic)
    car OpenAlex classe souvent en plusieurs sujets avec des scores.
    Tous les champs sont optionnels par défensivité (données réelles
    parfois incomplètes).
    """

    model_config = ConfigDict(extra="allow")

    domain: str | None = None
    field: str | None = None
    subfield: str | None = None
    topic: str | None = None
    score: float | None = None


class ThesesTopics(BaseModel):
    """Topics au format theses.fr : discipline + termes Rameau.

    `discipline` est une copie de `meta.discipline` — il est redondant
    mais présent dans les données historiques. Voir PublicationMeta.
    """

    model_config = ConfigDict(extra="allow")

    discipline: str | None = None
    rameau: list[str] | None = None


class PublicationTopics(BaseModel):
    """Modèle de la colonne JSONB `topics` (sur publications,
    reconstituée par refresh_from_sources).

    **Container composite par source** — chaque source garde sa forme
    native, rien n'est perdu (cf. commit précédent qui a corrigé
    la perte silencieuse des topics OpenAlex) :
    - openalex : liste de OpenAlexTopic (hiérarchie thématique)
    - theses   : dict discipline+rameau
    - scanr    : dict non contrôlé (structure variable)

    Sur `source_publications.topics`, chaque ligne contient UNE seule
    forme (la forme native de la source). Sur `publications.topics`,
    le dict indexé par source est reconstitué à partir des sources.
    """

    model_config = ConfigDict(extra="allow")

    openalex: list[OpenAlexTopic] | None = None
    theses: ThesesTopics | None = None
    # ScanR a un format variable côté API, non figé en sous-modèle
    # Pydantic. `Any` justifié : payload JSON brut conservé en JSONB.
    scanr: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Sérialise pour écriture en base (colonne JSONB `topics`). `Any`
        justifié : sortie destinée à une colonne JSONB."""
        return self.model_dump(exclude_none=True)
