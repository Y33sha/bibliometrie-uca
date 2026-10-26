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

    `search` cherche dans le titre et dans les ISSN — les trois colonnes de support et les ISSN rejetés. `serial_types` et `oa_models` sont multi-valués : une option cochée s'ajoute aux autres. `with_publications` restreint aux revues qui ont au moins une publication.
    """

    search: str = ""
    publisher_id: int | None = None
    serial_types: list[str] = field(default_factory=list)
    is_in_doaj: bool | None = None
    oa_models: list[str] = field(default_factory=list)
    with_publications: bool = False


class SerialIssnDetail(BaseModel):
    """Un ISSN d'une revue : support, ISSN-L, statut, ISSN successeur et date de vérification au Sudoc."""

    issn: str
    support: IssnSupport | None
    linking: bool
    status: IssnStatus
    sudoc_checked_at: datetime | None


class SerialListItem(BaseModel):
    """Ligne de la liste paginée `/api/serials` — un résumé ; le profil complet est `SerialDetailResponse`.

    `publisher_name` est joint depuis `publishers`, `publication_count` est un agrégat sur `publications` ; ni l'un ni l'autre ne sont des colonnes natives de la table `serials`.
    """

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

    Étend la ligne de liste des champs propres au détail (ISSN-L, identifiants, modèle OA), plus la réponse DOAJ brute et sa date d'import. Le payload est exposé tel quel : son exploration précède le choix des colonnes typées qu'on en tirerait.
    """

    issn_details: list[SerialIssnDetail]
    openalex_id: str | None
    oa_model: OaModel | None
    is_academic: bool | None
    doaj_payload: dict[str, str] | None
    doaj_imported_at: datetime | None


class DocTypeCount(BaseModel):
    """Compteur de publications par `doc_type` pour une revue.

    `expected` est vrai si ce `doc_type` figure parmi les valeurs attendues pour le `serial_type` de la revue (`domain.serials.expected`), ce qui laisse le frontend signaler les autres.
    """

    doc_type: str | None
    count: int
    expected: bool


class OaStatusCount(BaseModel):
    """Compteur de publications par `oa_status` pour une revue.

    `expected` est vrai si ce `oa_status` figure parmi les valeurs attendues pour le `oa_model` de la revue (`domain.serials.expected`).
    """

    oa_status: str | None
    count: int
    expected: bool


class SerialsFacetsResponse(BaseModel):
    """Facettes de `/api/serials` sur trois dimensions.

    Chaque dimension écarte son propre filtre de la condition WHERE, de sorte que son décompte annonce le nombre de revues atteignables si l'option était cochée ou décochée. `label` reprend `SERIAL_TYPE_LABELS_FR` ou `OA_MODEL_LABELS_FR` selon la dimension ; la facette DOAJ expose `Indexée` / `Non indexée`.
    """

    serial_types: list[FacetOption]
    oa_models: list[FacetOption]
    doaj: list[FacetOption]


class SerialDashboardResponse(BaseModel):
    """GET /api/serials/{id}/dashboard : distributions des publications d'une revue.

    Les compteurs sont bruts, `None` et `unknown` compris : c'est à l'œil que se repèrent les incohérences, par exemple des publications `article` dans une revue de type `proceedings`.

    `expected_doc_types` et `expected_oa_statuses` listent les valeurs attendues pour le `serial_type` et le `oa_model` de la revue (`domain.serials.expected`), affichées au-dessus de chaque tableau. Elles sont vides quand la revue n'a pas la valeur correspondante, ou que celle-ci n'est pas mappée.
    """

    total_publications: int
    doc_types: list[DocTypeCount]
    oa_statuses: list[OaStatusCount]
    expected_doc_types: list[str]
    expected_oa_statuses: list[str]


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
    """Enregistrements de `record_serial` dont le DOI tombe dans l'espace de noms `namespace` de `namespace_serial`.

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
