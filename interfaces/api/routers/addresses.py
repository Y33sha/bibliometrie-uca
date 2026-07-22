"""Router des adresses brutes des sources : leur rattachement aux structures et l'attribution de leurs pays. Sert `/api/addresses/*`.

Les lectures passent par le port `AddressesQueries`, les écritures par les command handlers de `application.services.addresses.commands`, qui committent avant que le router ne rende la main. Le référentiel des pays, qui n'est pas une lecture d'adresse, vit dans `countries.py`.

Les routes sont groupées par sujet, et dans chaque groupe les chemins littéraux précèdent ceux qui portent un identifiant — un chemin littéral déclaré après `/{addr_id}` s'y ferait absorber.
"""

from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.addresses_queries import (
    AddressCountriesFilters,
    AddressDetected,
    AddressesCountriesResponse,
    AddressesQueries,
    AddressListFilters,
    AddressListResponse,
    AddressStatsResponse,
    AddressValidation,
    StructurePredicate,
    StructurePredicateOperator,
    TextPredicate,
    TextPredicateMode,
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

router = APIRouter(prefix="/api/addresses", tags=["addresses"])

# Chaque occurrence répétée porte `<opérateur>:<charge>`. Le motif déclare la forme et le
# vocabulaire : FastAPI refuse l'occurrence malformée par un 422, et le contrat OpenAPI la publie.
TextPredicateParam = Annotated[str, Query(pattern=r"^(contains|not_contains):.+$")]
StructurePredicateParam = Annotated[str, Query(pattern=r"^(recognized|not_recognized):\d+(,\d+)*$")]


def _parse_text_predicates(raw: list[str]) -> tuple[TextPredicate, ...]:
    """Découpe les paramètres répétés `text=<mode>:<terme>`, dont la forme est déjà validée."""
    out: list[TextPredicate] = []
    for item in raw:
        mode, _, term = item.partition(":")
        out.append(TextPredicate(mode=cast(TextPredicateMode, mode), term=term))
    return tuple(out)


def _parse_structure_predicates(raw: list[str]) -> tuple[StructurePredicate, ...]:
    """Découpe les paramètres répétés `struct=<operateur>:<id>[,<id>…]`, dont la forme est déjà validée."""
    out: list[StructurePredicate] = []
    for item in raw:
        operator, _, ids_csv = item.partition(":")
        out.append(
            StructurePredicate(
                operator=cast(StructurePredicateOperator, operator),
                structure_ids=tuple(int(x) for x in ids_csv.split(",")),
            )
        )
    return tuple(out)


# ── Rattachement aux structures ──────────────────────────────────


@router.get("", response_model=AddressListResponse)
def list_addresses(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    detected: AddressDetected = Query("yes"),
    validation: AddressValidation = Query("pending"),
    text: list[TextPredicateParam] = Query(default=[]),
    struct: list[StructurePredicateParam] = Query(default=[]),
    queries: AddressesQueries = Depends(addresses_queries),
) -> AddressListResponse:
    """Liste les adresses rattachées à une structure, avec prédicats texte/structure composables."""
    text_predicates = _parse_text_predicates(text)
    structure_predicates = _parse_structure_predicates(struct)

    # `detected=yes` borne la lecture à la structure demandée ; `no` et `all` cherchent au
    # contraire les adresses qui ne lui sont pas rattachées, et portent donc sur toute la base.
    # Croisés avec `pending` ou `all`, qui laissent passer les centaines de milliers d'adresses
    # jamais arbitrées, ils demandent un balayage complet — là où `confirmed` et `rejected` se
    # limitent à ce qu'une main a tranché pour cette structure. Un prédicat de texte ou de
    # structure suffit à réduire l'ensemble ; sans lui, la lecture est refusée.
    has_narrowing = bool(text_predicates) or bool(structure_predicates)
    if detected in ("no", "all") and not has_narrowing and validation in ("all", "pending"):
        return AddressListResponse(
            total=0,
            page=page,
            per_page=per_page,
            addresses=[],
            requires_search=True,
        )

    filters = AddressListFilters(
        detected=detected,
        validation=validation,
        text_predicates=text_predicates,
        structure_predicates=structure_predicates,
    )
    return queries.list_addresses(
        structure_id=structure_id, filters=filters, page=page, per_page=per_page
    )


@router.get("/stats", response_model=AddressStatsResponse)
def address_stats(
    structure_id: int = Query(...),
    queries: AddressesQueries = Depends(addresses_queries),
) -> AddressStatsResponse:
    """Compteurs d'adresses par état de détection et de validation, pour une structure."""
    return queries.address_stats(structure_id)


@router.post("/batch-review", response_model=BatchUpdatedResponse)
def batch_review(
    data: BatchReviewAction,
    bg: BackgroundTasks,
    conn: Connection = Depends(db_conn),
    addr_repo: AddressRepository = Depends(address_repo),
) -> BatchUpdatedResponse:
    """Confirme, rejette ou réinitialise le lien d'un lot d'adresses à une même structure."""
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


@router.get("/{addr_id}/publications", response_model=AddressPublicationsResponse)
def get_address_publications(
    addr_id: int,
    limit: int = Query(20, ge=1, le=100),
    queries: AddressesQueries = Depends(addresses_queries),
) -> AddressPublicationsResponse:
    """Échantillon de publications liées à une adresse."""
    raw_text = queries.get_address_raw_text(addr_id)
    if raw_text is None:
        raise HTTPException(status_code=404, detail="Adresse introuvable")
    publications = queries.get_address_publications(addr_id, limit)
    return AddressPublicationsResponse(
        address_id=addr_id, raw_text=raw_text, publications=publications
    )


@router.post("/{addr_id}/review", response_model=AddressReviewResponse)
def review_address(
    addr_id: int,
    action: ReviewAction,
    bg: BackgroundTasks,
    conn: Connection = Depends(db_conn),
    queries: AddressesQueries = Depends(addresses_queries),
    addr_repo: AddressRepository = Depends(address_repo),
) -> AddressReviewResponse:
    """Confirme, rejette ou réinitialise le lien entre une adresse et une structure.

    Renvoie 404 sur une adresse introuvable, que l'écriture traiterait sinon en silence.
    """
    if not queries.address_exists(addr_id):
        raise HTTPException(status_code=404, detail="Adresse introuvable")
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
        is_confirmed=link.is_confirmed if link else None,
        is_detected=link.is_detected if link else False,
        structures=structures,
    )


# ── Attribution des pays ─────────────────────────────────────────


@router.get("/countries", response_model=AddressesCountriesResponse)
def list_addresses_countries(
    search: str = Query(""),
    has_country: bool | None = Query(None),
    country_code: str = Query(""),
    suggested_country: str = Query(""),
    suggest: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
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


@router.post("/batch-country", response_model=BatchCountryResponse)
def batch_set_country(
    body: BatchSetCountry,
    bg: BackgroundTasks,
    conn: Connection = Depends(db_conn),
    addr_repo: AddressRepository = Depends(address_repo),
) -> BatchCountryResponse:
    """Ajoute un pays à des adresses (par IDs ou par filtre).

    Renvoie 400 sur un code pays absent du référentiel — la chaîne vide comprise — et sur un appel par filtre qui n'en porte aucun (`batch_set_country_by_filter`).
    """
    updated, propagated, all_ids = address_commands.batch_set_country(
        conn,
        body.country_code,
        address_ids=body.address_ids,
        search=body.search,
        has_country=body.has_country,
        country_code_filter=body.country_code_filter,
        suggested_country=body.suggested_country,
        repo=addr_repo,
    )
    bg.add_task(bg_propagate_countries, all_ids)
    return BatchCountryResponse(updated=updated, propagated=propagated)


@router.post("/{addr_id}/country", response_model=OkResponse)
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
