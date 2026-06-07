"""Router /api/addresses/* et /api/countries.

Lectures : port `AddressesQueries`. Mutations : services applicatifs
- `application.addresses_structures` pour les liens adresse↔structure
- `application.addresses_countries` pour l'attribution et propagation des pays.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from application.addresses import countries as countries_service
from application.addresses import structures as structures_service
from application.ports.api.addresses_queries import (
    AddressCountriesFilters,
    AddressesCountriesResponse,
    AddressesQueries,
    AddressListFilters,
    AddressListResponse,
    AddressStatsResponse,
    CountryOut,
    CountrySuggestionsResponse,
    StructurePredicate,
    TextPredicate,
)
from application.ports.repositories.address_repository import AddressRepository
from interfaces.api.deps import (
    address_repo_sync,
    addresses_queries_sync,
    bg_propagate_countries_sync,
    bg_propagate_in_perimeter_sync,
    require_admin,
)
from interfaces.api.models import (
    AddressPublicationsResponse,
    AddressReviewResponse,
    BatchCountryResponse,
    BatchReviewAction,
    BatchSetCountry,
    BatchUpdatedResponse,
    OkResponse,
    ReviewAction,
    SetCountry,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_TEXT_MODES = {"contains", "not_contains"}
_STRUCT_OPS = {"recognized", "not_recognized"}


def _parse_text_predicates(raw: list[str]) -> tuple[TextPredicate, ...]:
    """Parse les params répétés `text=<mode>:<terme>` (cf. fiche, décision 8).

    Tolérant : mode inconnu ou terme vide → prédicat ignoré.
    """
    out: list[TextPredicate] = []
    for item in raw:
        mode, _, term = item.partition(":")
        term = term.strip()
        if mode in _TEXT_MODES and term:
            out.append(TextPredicate(mode=mode, term=term))
    return tuple(out)


def _parse_structure_predicates(raw: list[str]) -> tuple[StructurePredicate, ...]:
    """Parse les params répétés `struct=<operator>:<id>[,<id>…]`.

    Tolérant : opérateur inconnu ou aucun id valide → prédicat ignoré.
    """
    out: list[StructurePredicate] = []
    for item in raw:
        op, _, ids_csv = item.partition(":")
        if op not in _STRUCT_OPS:
            continue
        ids = tuple(int(x) for x in (s.strip() for s in ids_csv.split(",")) if x.isdigit())
        if ids:
            out.append(StructurePredicate(operator=op, structure_ids=ids))
    return tuple(out)


@router.get("/api/addresses", response_model=AddressListResponse)
def list_addresses(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    structure_id: int | None = Query(None),
    detected: str = Query("yes"),
    validation: str = Query("pending"),
    text: list[str] = Query(default=[]),
    struct: list[str] = Query(default=[]),
    search: str = Query(""),  # legacy (transition phase 1→2) → un prédicat texte
    search_mode: str = Query("contains"),
    queries: AddressesQueries = Depends(addresses_queries_sync),
) -> AddressListResponse:
    """Liste les adresses pour une structure, avec prédicats texte/structure composables."""
    text_predicates = _parse_text_predicates(text)
    if search:
        text_predicates = (TextPredicate(mode=search_mode, term=search), *text_predicates)
    structure_predicates = _parse_structure_predicates(struct)

    # Garde-fou : mode "non détecté"/"tous" sans aucun prédicat de réduction → trop large.
    has_narrowing = bool(text_predicates) or bool(structure_predicates)
    if detected in ("no", "all") and not has_narrowing and validation in ("all", "pending"):
        return AddressListResponse(
            total=0,
            page=1,
            per_page=per_page,
            pages=0,
            addresses=[],
            requires_search=True,
        )

    filters = AddressListFilters(
        detected=detected,
        validation=validation,
        text_predicates=text_predicates,
        structure_predicates=structure_predicates,
    )
    sid = structure_id if structure_id is not None else queries.resolve_default_structure_id()
    return queries.list_addresses(structure_id=sid, filters=filters, page=page, per_page=per_page)


@router.get("/api/addresses/{addr_id}/publications", response_model=AddressPublicationsResponse)
def get_address_publications(
    addr_id: int,
    limit: int = Query(20),
    queries: AddressesQueries = Depends(addresses_queries_sync),
) -> AddressPublicationsResponse:
    """Échantillon de publications liées à une adresse."""
    raw_text = queries.get_address_raw_text(addr_id)
    if not raw_text:
        raise HTTPException(status_code=404, detail="Address not found")
    publications = queries.get_address_publications(addr_id, limit)
    return AddressPublicationsResponse(
        address_id=addr_id, raw_text=raw_text, publications=publications
    )


@router.post("/api/addresses/{addr_id}/review", response_model=AddressReviewResponse)
def review_address(
    addr_id: int,
    action: ReviewAction,
    bg: BackgroundTasks,
    queries: AddressesQueries = Depends(addresses_queries_sync),
    addr_repo: AddressRepository = Depends(address_repo_sync),
) -> AddressReviewResponse:
    """Confirme, rejette ou reset le lien adresse ↔ structure."""
    changed = structures_service.review_structure_link(
        addr_id,
        action.structure_id,
        action.is_confirmed,
        repo=addr_repo,
    )
    if changed:
        bg.add_task(bg_propagate_in_perimeter_sync, changed)
    structures = queries.get_address_structures(addr_id)
    link = queries.get_structure_link(addr_id, action.structure_id)
    return AddressReviewResponse(
        id=addr_id,
        is_confirmed=link["is_confirmed"] if link else None,
        is_detected=link["is_detected"] if link else False,
        structures=structures,
    )


@router.post("/api/addresses/batch-review", response_model=BatchUpdatedResponse)
def batch_review(
    data: BatchReviewAction,
    bg: BackgroundTasks,
    addr_repo: AddressRepository = Depends(address_repo_sync),
) -> BatchUpdatedResponse:
    """Confirme/rejette/reset en batch."""
    updated, changed = structures_service.batch_review_structure_link(
        data.address_ids,
        data.structure_id,
        data.is_confirmed,
        repo=addr_repo,
    )
    if changed:
        bg.add_task(bg_propagate_in_perimeter_sync, changed)
    return BatchUpdatedResponse(updated=updated)


@router.get("/api/countries", response_model=list[CountryOut])
def list_countries(
    queries: AddressesQueries = Depends(addresses_queries_sync),
) -> list[CountryOut]:
    """Liste des pays."""
    return queries.list_countries()


@router.get("/api/addresses/countries", response_model=AddressesCountriesResponse)
def list_addresses_countries(
    search: str = Query(""),
    has_country: str = Query(""),
    country_code: str = Query(""),
    suggested_country: str = Query(""),
    suggest: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: AddressesQueries = Depends(addresses_queries_sync),
) -> AddressesCountriesResponse:
    """Liste des adresses pour l'attribution de pays."""
    filters = AddressCountriesFilters(
        search=search,
        has_country=has_country,
        country_code=country_code,
        suggested_country=suggested_country,
        suggest=suggest,
    )
    return queries.addresses_countries(filters=filters, page=page, per_page=per_page)


@router.get("/api/addresses/suggest-countries", response_model=CountrySuggestionsResponse)
def suggest_countries(
    search: str = Query(""),
    queries: AddressesQueries = Depends(addresses_queries_sync),
    _: None = Depends(require_admin),
) -> CountrySuggestionsResponse:
    """Distribution des pays des adresses matchantes + compte des sans-pays."""
    return queries.suggest_countries(search)


@router.post("/api/addresses/{addr_id}/country", response_model=OkResponse)
def set_address_country(
    addr_id: int,
    body: SetCountry,
    bg: BackgroundTasks,
    queries: AddressesQueries = Depends(addresses_queries_sync),
    addr_repo: AddressRepository = Depends(address_repo_sync),
    _: None = Depends(require_admin),
) -> OkResponse:
    """Attribue des pays à une adresse."""
    if not queries.address_exists(addr_id):
        raise HTTPException(status_code=404, detail="Adresse introuvable")
    for c in body.countries or []:
        if not queries.country_exists(c):
            raise HTTPException(status_code=400, detail=f"Code pays inconnu: {c}")

    affected = countries_service.set_country(addr_id, body.countries, repo=addr_repo)
    bg.add_task(bg_propagate_countries_sync, affected)
    return OkResponse()


@router.post("/api/addresses/batch-country", response_model=BatchCountryResponse)
def batch_set_country(
    body: BatchSetCountry,
    bg: BackgroundTasks,
    queries: AddressesQueries = Depends(addresses_queries_sync),
    addr_repo: AddressRepository = Depends(address_repo_sync),
    _: None = Depends(require_admin),
) -> BatchCountryResponse:
    """Ajoute un pays à des adresses (par IDs ou par filtre)."""
    country_code = body.country_code
    if not country_code:
        raise HTTPException(status_code=400, detail="country_code requis")

    if not queries.country_exists(country_code):
        raise HTTPException(status_code=400, detail=f"Code pays inconnu: {country_code}")

    if body.address_ids:
        modified_ids = countries_service.batch_set_country_by_ids(
            country_code, body.address_ids, repo=addr_repo
        )
    else:
        modified_ids = countries_service.batch_set_country_by_filter(
            country_code,
            search=body.search,
            has_country=body.has_country,
            country_code_filter=body.country_code_filter,
            suggested_country=body.suggested_country,
            repo=addr_repo,
        )
    updated = len(modified_ids)

    propagated_ids = countries_service.propagate_countries_to_similar(
        modified_ids=modified_ids, repo=addr_repo
    )
    propagated = len(propagated_ids)
    all_ids = modified_ids + propagated_ids

    bg.add_task(bg_propagate_countries_sync, all_ids)
    return BatchCountryResponse(updated=updated, propagated=propagated)


@router.get("/api/admin/address-stats", response_model=AddressStatsResponse)
def admin_address_stats(
    structure_id: int | None = Query(None),
    queries: AddressesQueries = Depends(addresses_queries_sync),
) -> AddressStatsResponse:
    """Compteurs d'adresses par détection/validation pour une structure."""
    if structure_id is None:
        structure_id = queries.resolve_default_structure_id()
    return queries.admin_address_stats(structure_id)
