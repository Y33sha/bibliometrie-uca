"""Router /api/addresses/* et /api/countries — les adresses brutes des sources, leur rattachement aux structures et leurs pays.

Les lectures passent par le port `AddressesQueries`, les écritures par les command handlers de `application.services.addresses.commands`, qui committent avant que le router ne rende la main.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import Connection

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
from application.services.addresses import commands as address_commands
from interfaces.api.deps import (
    address_repo,
    addresses_queries,
    bg_propagate_countries,
    bg_propagate_in_perimeter,
    db_conn,
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

_TEXT_MODES = {"contains", "not_contains"}
_STRUCT_OPS = {"recognized", "not_recognized"}


def _parse_text_predicates(raw: list[str]) -> tuple[TextPredicate, ...]:
    """Lit les paramètres répétés `text=<mode>:<terme>`, dont les modes sont `contains` et `not_contains`.

    La lecture est tolérante : un mode inconnu ou un terme vide laisse tomber le prédicat plutôt que de refuser la requête.
    """
    out: list[TextPredicate] = []
    for item in raw:
        mode, _, term = item.partition(":")
        term = term.strip()
        if mode in _TEXT_MODES and term:
            out.append(TextPredicate(mode=mode, term=term))
    return tuple(out)


def _parse_structure_predicates(raw: list[str]) -> tuple[StructurePredicate, ...]:
    """Lit les paramètres répétés `struct=<operateur>:<id>[,<id>…]`, dont les opérateurs sont `recognized` et `not_recognized`.

    La lecture est tolérante : un opérateur inconnu ou une liste sans identifiant valide laisse tomber le prédicat plutôt que de refuser la requête.
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
    queries: AddressesQueries = Depends(addresses_queries),
) -> AddressListResponse:
    """Liste les adresses pour une structure, avec prédicats texte/structure composables."""
    text_predicates = _parse_text_predicates(text)
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
    queries: AddressesQueries = Depends(addresses_queries),
) -> AddressPublicationsResponse:
    """Échantillon de publications liées à une adresse."""
    raw_text = queries.get_address_raw_text(addr_id)
    if not raw_text:
        raise HTTPException(status_code=404, detail="Adresse introuvable")
    publications = queries.get_address_publications(addr_id, limit)
    return AddressPublicationsResponse(
        address_id=addr_id, raw_text=raw_text, publications=publications
    )


@router.post("/api/addresses/{addr_id}/review", response_model=AddressReviewResponse)
def review_address(
    addr_id: int,
    action: ReviewAction,
    bg: BackgroundTasks,
    conn: Connection = Depends(db_conn),
    queries: AddressesQueries = Depends(addresses_queries),
    addr_repo: AddressRepository = Depends(address_repo),
) -> AddressReviewResponse:
    """Confirme, rejette ou reset le lien adresse ↔ structure."""
    changed = address_commands.review_structure_link(
        conn,
        addr_id,
        action.structure_id,
        action.is_confirmed,
        repo=addr_repo,
    )
    if changed:
        bg.add_task(bg_propagate_in_perimeter, changed)
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
    conn: Connection = Depends(db_conn),
    addr_repo: AddressRepository = Depends(address_repo),
) -> BatchUpdatedResponse:
    """Confirme/rejette/reset en batch."""
    updated, changed = address_commands.batch_review_structure_link(
        conn,
        data.address_ids,
        data.structure_id,
        data.is_confirmed,
        repo=addr_repo,
    )
    if changed:
        bg.add_task(bg_propagate_in_perimeter, changed)
    return BatchUpdatedResponse(updated=updated)


@router.get("/api/countries", response_model=list[CountryOut])
def list_countries(
    queries: AddressesQueries = Depends(addresses_queries),
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
    queries: AddressesQueries = Depends(addresses_queries),
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
    queries: AddressesQueries = Depends(addresses_queries),
) -> CountrySuggestionsResponse:
    """Distribution des pays des adresses matchantes + compte des sans-pays."""
    return queries.suggest_countries(search)


@router.post("/api/addresses/{addr_id}/country", response_model=OkResponse)
def set_address_country(
    addr_id: int,
    body: SetCountry,
    bg: BackgroundTasks,
    conn: Connection = Depends(db_conn),
    addr_repo: AddressRepository = Depends(address_repo),
) -> OkResponse:
    """Attribue des pays à une adresse.

    Renvoie 400 sur un code pays absent du référentiel, 404 sur une adresse introuvable (`set_country`).
    """
    affected = address_commands.set_country(conn, addr_id, body.countries, repo=addr_repo)
    bg.add_task(bg_propagate_countries, affected)
    return OkResponse()


@router.post("/api/addresses/batch-country", response_model=BatchCountryResponse)
def batch_set_country(
    body: BatchSetCountry,
    bg: BackgroundTasks,
    conn: Connection = Depends(db_conn),
    queries: AddressesQueries = Depends(addresses_queries),
    addr_repo: AddressRepository = Depends(address_repo),
) -> BatchCountryResponse:
    """Ajoute un pays à des adresses (par IDs ou par filtre).

    Renvoie 400 sur un code pays absent du référentiel — la chaîne vide comprise — et sur un appel par filtre qui n'en porte aucun (`batch_set_country_by_filter`).
    """
    country_code = body.country_code
    updated, propagated, all_ids = address_commands.batch_set_country(
        conn,
        country_code,
        address_ids=body.address_ids,
        search=body.search,
        has_country=body.has_country,
        country_code_filter=body.country_code_filter,
        suggested_country=body.suggested_country,
        repo=addr_repo,
    )

    bg.add_task(bg_propagate_countries, all_ids)
    return BatchCountryResponse(updated=updated, propagated=propagated)


@router.get("/api/admin/address-stats", response_model=AddressStatsResponse)
def admin_address_stats(
    structure_id: int | None = Query(None),
    queries: AddressesQueries = Depends(addresses_queries),
) -> AddressStatsResponse:
    """Compteurs d'adresses par détection/validation pour une structure."""
    if structure_id is None:
        structure_id = queries.resolve_default_structure_id()
    return queries.admin_address_stats(structure_id)
