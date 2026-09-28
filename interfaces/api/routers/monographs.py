"""Router des monographies : liste, facettes et fiche. Sert `/api/monographs/*`.

Les chemins littéraux `/facets` et `/facets/entities` précèdent `/{monograph_id}`, qui l'accepterait sinon comme identifiant.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.read_models._common import EntityFacetResponse
from application.ports.read_models.monographs_queries import (
    MONOGRAPH_KINDS,
    MonographEntityKind,
    MonographFilters,
    MonographListItem,
    MonographListResponse,
    MonographQueries,
    MonographsFacetsResponse,
    MonographSort,
)
from interfaces.api.deps import monograph_queries
from interfaces.api.filters import parse_int_csv, parse_vocabulary_csv
from interfaces.api.params import SearchTerm

router = APIRouter(prefix="/api/monographs", tags=["monographs"])


def monograph_filters(
    search: SearchTerm = "",
    monograph_type: str = Query("", alias="type"),
    year: str = "",
    publisher_id: int | None = None,
    journal_id: int | None = None,
) -> MonographFilters:
    """Filtres partagés par la liste et ses facettes.

    `search` porte sur le titre, ou sur l'ISBN quand le terme commence par 978 ou 979. `type` liste, séparés par des virgules, les types retenus : `book` (livre), `proceedings` (volume d'actes). `year` liste les années retenues. `publisher_id` et `journal_id` restreignent à un éditeur et à une collection.
    """
    kinds = parse_vocabulary_csv(monograph_type, allowed=MONOGRAPH_KINDS, param="type")
    return MonographFilters(
        search=search,
        kinds=tuple(kinds),
        years=tuple(parse_int_csv(year, param="year")),
        publisher_id=publisher_id,
        journal_id=journal_id,
    )


@router.get("", response_model=MonographListResponse)
def list_monographs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: MonographSort = "pubs_desc",
    filters: MonographFilters = Depends(monograph_filters),
    queries: MonographQueries = Depends(monograph_queries),
) -> MonographListResponse:
    """Liste paginée des monographies, avec leur éditeur, leur collection et le nombre de publications qu'elles contiennent."""
    return queries.list_monographs(filters=filters, sort=sort, page=page, per_page=per_page)


@router.get("/facets", response_model=MonographsFacetsResponse)
def monographs_facets(
    filters: MonographFilters = Depends(monograph_filters),
    queries: MonographQueries = Depends(monograph_queries),
) -> MonographsFacetsResponse:
    """Nombre de monographies par type et par année. Chaque décompte écarte le filtre de sa dimension."""
    return queries.monographs_facets(filters=filters)


@router.get("/facets/entities", response_model=EntityFacetResponse)
def monographs_entity_facet(
    kind: MonographEntityKind = Query(...),
    entity_search: SearchTerm = "",
    filters: MonographFilters = Depends(monograph_filters),
    queries: MonographQueries = Depends(monograph_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs ou des collections : les premiers sous les filtres actifs, avec leur nombre de monographies.

    `entity_search` cherche dans les noms d'éditeur ou les titres de collection, là où `search` filtre les monographies.
    """
    return queries.monographs_entity_facet(kind=kind, search=entity_search, filters=filters)


@router.get("/{monograph_id}", response_model=MonographListItem)
def get_monograph(
    monograph_id: int,
    queries: MonographQueries = Depends(monograph_queries),
) -> MonographListItem:
    """Fiche d'une monographie. Renvoie 404 sur une monographie inconnue."""
    row = queries.get_monograph(monograph_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Monographie introuvable")
    return row
