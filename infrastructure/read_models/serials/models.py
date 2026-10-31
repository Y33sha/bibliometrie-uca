"""Modèles de réponse : lectures sur les revues."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from application.ports.model import Model
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
    """Filtres communs à la liste des revues et à ses facettes."""

    search: str = ""
    """Terme cherché dans le titre, et dans tous les ISSN de la revue, quel que soit leur statut."""
    publisher_id: int | None = None
    serial_types: list[str] = field(default_factory=list)
    """Multi-valué : une option cochée s'ajoute aux autres."""
    is_in_doaj: bool | None = None
    oa_models: list[str] = field(default_factory=list)
    """Multi-valué : une option cochée s'ajoute aux autres."""
    has_publications: bool | None = None
    """Retient les revues à au moins une publication (`True`) ou sans publication (`False`)."""


class SerialIssnDetail(Model):
    """ISSN d'une revue, avec son support, son statut et sa date de vérification au Sudoc."""

    issn: str
    support: IssnSupport | None
    linking: bool
    """ISSN de liaison (ISSN-L)."""
    status: IssnStatus
    sudoc_checked_at: datetime | None


class SerialRelation(Model):
    """Revue liée par un lien Sudoc entre ISSN (`issn_links`)."""

    kind: Literal["previous_title", "next_title", "supplement", "main_serial"]
    """Titre précédent, titre suivant, supplément de la revue, ou revue dont elle est le supplément."""
    serial_id: int | None
    """Revue de l'ISSN lié, `None` pour un ISSN sans revue."""
    title: str | None
    issn: str | None
    """ISSN lié, quand il est sans revue."""


class SerialListItem(Model):
    """Ligne de la liste paginée `/api/serials`, résumé du profil complet (`SerialDetailResponse`)."""

    id: int
    title: str
    issns: list[str]
    """ISSN actifs."""
    publisher_id: int | None
    publisher_name: str | None
    is_in_doaj: bool
    serial_type: SerialType | None
    oa_model: OaModel | None
    publication_count: int
    doaj_url: str | None


class SerialListResponse(PaginatedResponse):
    serials: list[SerialListItem]


class SerialDetailResponse(SerialListItem):
    """Profil complet de la revue (GET /api/serials/{id}), pour sa page publique et l'édition admin : la ligne de liste et les champs propres au détail."""

    issn_details: list[SerialIssnDetail]
    relations: list[SerialRelation]
    openalex_id: str | None
    is_academic: bool | None
    doaj_payload: dict[str, str] | None
    """Réponse DOAJ brute, renvoyée telle quelle."""
    doaj_imported_at: datetime | None


class SerialsFacetsResponse(Model):
    """Facettes de `/api/serials`.

    Chaque dimension écarte son propre filtre de la condition WHERE : son décompte donne le nombre de revues retenues si l'option est cochée ou décochée.
    """

    serial_types: list[FacetOption]
    """Libellés tirés de `SERIAL_TYPE_LABELS_FR`."""
    oa_models: list[FacetOption]
    """Libellés tirés de `OA_MODEL_LABELS_FR`."""
    doaj: list[FacetOption]
    """Libellés `Indexée` et `Non indexée`."""
    publications: YesNoCount
    """Revues avec et sans publication."""


class SerialDuplicateGroup(Model):
    """Groupe de revues en double potentiel, la plus riche en publications en tête."""

    value: str
    """Titre normalisé, ou ISSN actif dans chacune des revues."""
    serials: list[SerialListItem]


class SerialDuplicatesResponse(Model):
    """File de groupes de revues en double potentiel, les plus riches en publications en tête."""

    groups: list[SerialDuplicateGroup]


class LikelyProceedingsItem(Model):
    """Revue typée `journal` contenant surtout des articles de congrès, d'après le type donné par chaque source."""

    serial: SerialListItem
    conference_papers: int
    """Enregistrements sources typés article de congrès."""
    records: int
    """Enregistrements sources de la revue."""


class LikelyProceedingsResponse(Model):
    """File des recueils d'actes probables : les revues sans ISSN en tête, puis les plus riches en enregistrements sources."""

    serials: list[LikelyProceedingsItem]


class DoiNamespaceConflict(Model):
    """Enregistrements sources de `record_serial` dont le DOI relève de l'espace de noms `namespace` de `namespace_serial`."""

    namespace: str
    dois: int
    """DOI distincts de l'espace de noms."""
    documents: int
    """Enregistrements sources de l'espace de noms."""
    share: float
    """Part des DOI de l'espace de noms désignant `namespace_serial` ; un DOI partagé entre plusieurs revues compte au prorata de ses enregistrements sources."""
    namespace_serial: SerialListItem
    record_serial: SerialListItem
    records: int
    """Enregistrements sources de `record_serial`."""
    sources: dict[str, int]
    """Répartition de `records` par source."""


class DoiNamespaceConflictsResponse(Model):
    """Paires de revues contredites par les espaces de noms DOI, les plus fournies en enregistrements sources d'abord."""

    conflicts: list[DoiNamespaceConflict]
