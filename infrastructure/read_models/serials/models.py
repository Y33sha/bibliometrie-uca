"""Modèles de réponse : lectures sur les revues."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from domain.serials.issns import IssnStatus, IssnSupport
from domain.serials.serial import OaModel, SerialType
from infrastructure.read_models._common import (
    FacetOption,
    PaginatedResponse,
    YesNoCount,
)

# Vocabulaire de tri de la liste des revues : le champ, puis le sens.
SerialSort = Literal[
    "title_asc",
    "title_desc",
    "publisher_asc",
    "publisher_desc",
    "publications_asc",
    "publications_desc",
]


@dataclass(frozen=True, slots=True)
class SerialFilters:
    """Filtres que la liste des revues et ses facettes honorent toutes deux.

    `search` cherche dans le titre, et dans tous les ISSN de la revue, quel que soit leur statut. `serial_types` et `oa_models` sont multi-valués : une option cochée s'ajoute aux autres. `has_publications` retient les revues qui ont au moins une publication (`True`) ou aucune (`False`).
    """

    search: str = ""
    publisher_id: int | None = None
    serial_types: list[str] = field(default_factory=list)
    is_in_doaj: bool | None = None
    oa_models: list[str] = field(default_factory=list)
    has_publications: bool | None = None


class SerialIssnDetail(BaseModel):
    """Un ISSN d'une revue : support, ISSN-L, statut, ISSN successeur et date de vérification au Sudoc."""

    issn: str
    support: IssnSupport | None
    linking: bool
    status: IssnStatus
    sudoc_checked_at: datetime | None


class SerialListItem(BaseModel):
    """Ligne de la liste paginée `/api/serials`, résumé du profil complet (`SerialDetailResponse`). Le nom de l'éditeur vient de `publishers`, le nombre de publications des publications."""

    id: int
    title: str
    issns: list[str]
    """ISSN actifs."""
    publisher_id: int | None
    publisher_name: str | None
    is_in_doaj: bool
    serial_type: SerialType | None
    publication_count: int
    doaj_url: str | None


class SerialListResponse(PaginatedResponse):
    serials: list[SerialListItem]


class SerialDetailResponse(SerialListItem):
    """GET /api/serials/{id} : profil complet de la revue, pour sa page publique et l'édition admin.

    Étend la ligne de liste des champs propres au détail (ISSN-L, identifiants, modèle OA), plus la réponse DOAJ brute et sa date d'import. Le payload DOAJ est rendu tel quel.
    """

    issn_details: list[SerialIssnDetail]
    openalex_id: str | None
    oa_model: OaModel | None
    is_academic: bool | None
    doaj_payload: dict[str, str] | None
    doaj_imported_at: datetime | None


class SerialsFacetsResponse(BaseModel):
    """Facettes de `/api/serials`.

    Chaque dimension écarte son propre filtre de la condition WHERE, de sorte que son décompte annonce le nombre de revues atteignables si l'option était cochée ou décochée. `label` reprend `SERIAL_TYPE_LABELS_FR` ou `OA_MODEL_LABELS_FR` selon la dimension ; la facette DOAJ a pour libellés `Indexée` et `Non indexée`. `publications` compte les revues avec et sans publication.
    """

    serial_types: list[FacetOption]
    oa_models: list[FacetOption]
    doaj: list[FacetOption]
    publications: YesNoCount


class SerialDuplicateGroup(BaseModel):
    """Revues en double potentiel : la valeur qu'elles partagent, puis les revues, la plus riche en publications en tête."""

    value: str
    """Titre normalisé, ou ISSN actif dans chacune des revues."""
    serials: list[SerialListItem]


class SerialDuplicatesResponse(BaseModel):
    """File de groupes de revues en double potentiel, les plus riches en publications en tête."""

    groups: list[SerialDuplicateGroup]


class LikelyProceedingsItem(BaseModel):
    """Revue typée `journal` qui contient surtout des articles de congrès : `conference_papers` sur `records` documents, d'après le type donné par chaque source."""

    serial: SerialListItem
    conference_papers: int
    records: int


class LikelyProceedingsResponse(BaseModel):
    """File des recueils d'actes probables : les revues sans ISSN en tête, puis les plus riches en documents."""

    serials: list[LikelyProceedingsItem]


class DoiNamespaceConflict(BaseModel):
    """Enregistrements de `record_serial` dont le DOI relève de l'espace de noms `namespace` de `namespace_serial`.

    `dois`, `documents` et `share` décrivent l'espace de noms : ses DOI distincts, ses enregistrements, et la part des DOI qui désigne `namespace_serial`, un DOI partagé entre plusieurs revues au prorata de ses enregistrements. `records` compte les enregistrements de `record_serial`, `sources` les répartit par source.
    """

    namespace: str
    dois: int
    documents: int
    share: float
    namespace_serial: SerialListItem
    record_serial: SerialListItem
    records: int
    sources: dict[str, int]


class DoiNamespaceConflictsResponse(BaseModel):
    """Paires de revues que contredisent les espaces de noms DOI, les plus fournies en enregistrements d'abord."""

    conflicts: list[DoiNamespaceConflict]
