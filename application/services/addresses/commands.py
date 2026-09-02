"""Command handlers des écritures API sur les adresses : frontière transactionnelle de l'agrégat.

Les briques d'écriture agnostiques vivent dans `structures.py` et `countries.py`. Les propagations potentiellement massives (`in_perimeter`, pays → publications) ne sont pas faites ici : le handler retourne les identifiants d'adresses concernés, que le routeur passe en tâche de fond. Le commit précède ces tâches, qui lisent l'état persisté.
"""

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.countries import CountryQueries
from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.audit_repository import AuditRepository
from application.services.addresses import (
    countries as countries_service,
    structure_links as structure_links_service,
)
from domain.types import JsonValue


def review_structure_link(
    conn: Connection,
    address_id: int,
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AddressRepository,
    audit_repo: AuditRepository | None = None,
) -> list[int]:
    """Valide un lien adresse ↔ structure. Retourne les adresses dont la
    contribution à `in_perimeter` a changé (à propager en tâche de fond)."""
    changed = structure_links_service.review_structure_link(
        address_id, structure_id, is_confirmed, repo=repo
    )
    emit_event(
        audit_repo,
        "address.link_reviewed",
        "address",
        address_id,
        {"structure_id": structure_id, "is_confirmed": is_confirmed},
    )
    conn.commit()
    return changed


def batch_review_structure_link(
    conn: Connection,
    address_ids: list[int],
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AddressRepository,
    audit_repo: AuditRepository | None = None,
) -> tuple[int, list[int]]:
    """Valide un lot de liens adresse ↔ structure. Retourne `(nombre d'adresses
    touchées, adresses dont la contribution à `in_perimeter` a changé)`.

    Un lot est une décision unique : l'événement d'audit est unique lui aussi, sans
    identifiant d'agrégat, et porte les adresses visées et le nombre effectivement touché.
    """
    updated, changed = structure_links_service.batch_review_structure_link(
        address_ids, structure_id, is_confirmed, repo=repo
    )
    if address_ids:
        emit_event(
            audit_repo,
            "address.batch_link_reviewed",
            "address",
            None,
            {
                "address_ids": address_ids,
                "structure_id": structure_id,
                "is_confirmed": is_confirmed,
                "updated": updated,
            },
        )
    conn.commit()
    return updated, changed


def set_country(
    conn: Connection,
    address_id: int,
    countries: list[str] | None,
    *,
    repo: AddressRepository,
    country_queries: CountryQueries,
    audit_repo: AuditRepository | None = None,
) -> list[int]:
    """Attribue des pays à une adresse. Retourne les adresses affectées (l'adresse
    et ses jumelles), à propager vers les publications en tâche de fond."""
    affected = countries_service.set_country(
        conn, address_id, countries, repo=repo, country_queries=country_queries
    )
    emit_event(
        audit_repo,
        "address.country_set",
        "address",
        address_id,
        {"countries": countries or [], "propagated": len(affected)},
    )
    conn.commit()
    return affected


def batch_set_country(
    conn: Connection,
    country_code: str,
    *,
    address_ids: list[int] | None,
    search: str,
    has_country: bool | None,
    country_code_filter: str,
    suggested_country: str,
    repo: AddressRepository,
    country_queries: CountryQueries,
    audit_repo: AuditRepository | None = None,
) -> tuple[int, int, list[int]]:
    """Ajoute un pays à des adresses (par identifiants ou par filtre), puis le
    propage aux adresses jumelles, en une seule transaction.

    Retourne `(adresses modifiées, adresses propagées, tous les identifiants
    concernés)` ; le dernier est à propager vers les publications en tâche de fond.
    """
    if address_ids:
        modified_ids = countries_service.batch_set_country_by_ids(
            conn, country_code, address_ids, repo=repo, country_queries=country_queries
        )
    else:
        modified_ids = countries_service.batch_set_country_by_filter(
            conn,
            country_code,
            search=search,
            has_country=has_country,
            country_code_filter=country_code_filter,
            suggested_country=suggested_country,
            repo=repo,
            country_queries=country_queries,
        )
    propagated_ids = countries_service.propagate_countries_to_similar(
        conn, modified_ids=modified_ids, country_queries=country_queries
    )
    # Une sélection par filtre peut couvrir toute la table : c'est le critère qui porte la
    # décision, non la liste qu'il rend. L'appel par identifiants, lui, les consigne.
    decision: dict[str, JsonValue] = {"country_code": country_code}
    if address_ids:
        decision["address_ids"] = address_ids
    else:
        decision["filtre"] = {
            "search": search,
            "has_country": has_country,
            "country_code_filter": country_code_filter,
            "suggested_country": suggested_country,
        }
    emit_event(
        audit_repo,
        "address.batch_country_set",
        "address",
        None,
        {**decision, "updated": len(modified_ids), "propagated": len(propagated_ids)},
    )
    conn.commit()
    return len(modified_ids), len(propagated_ids), modified_ids + propagated_ids
