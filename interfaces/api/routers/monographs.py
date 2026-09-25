"""Router des monographies : liste, facettes et fiche. Sert `/api/monographs/*`.

Le chemin littéral `/facets` précède `/{monograph_id}`, qui l'accepterait sinon comme identifiant.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.read_models.monographs_queries import (
    MONOGRAPH_KINDS,
    MonographFilters,
    MonographListItem,
    MonographListResponse,
    MonographQueries,
    MonographsFacetsResponse,
    MonographSort,
)
from interfaces.api.deps import monograph_queries
from interfaces.api.filters import parse_vocabulary_csv
from interfaces.api.params import SearchTerm

router = APIRouter(prefix="/api/monographs", tags=["monographs"])


def monograph_filters(
    search: SearchTerm = "",
    kind: str = "",
    publisher_id: int | None = None,
    journal_id: int | None = None,
) -> MonographFilters:
    """Filtres partagés par la liste et ses facettes.

    `search` porte sur le titre, ou sur l'ISBN quand le terme commence par 978 ou 979. `kind` liste, séparés par des virgules, les types retenus : `book` (livre), `proceedings` (volume d'actes). `publisher_id` et `journal_id` restreignent à un éditeur et à une collection.
    """
    kinds = parse_vocabulary_csv(kind, allowed=MONOGRAPH_KINDS, param="kind")
    return MonographFilters(
        search=search, kinds=tuple(kinds), publisher_id=publisher_id, journal_id=journal_id
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
    """Nombre de monographies par type. Le décompte écarte le filtre de type."""
    return queries.monographs_facets(filters=filters)


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
