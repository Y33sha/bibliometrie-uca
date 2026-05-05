"""
Service Pays des adresses — attribution, propagation horizontale
(adresses similaires) et verticale (vers source_publications /
publications).

Séparé de `application/addresses.py` (principe SRP) : la validation
des liens adresse↔structure vit dans
`application/addresses_structures.py`. Les deux surfaces partagent
l'agrégat Address mais n'interagissent pas entre elles.

Le SQL vit dans `infrastructure/repositories/address_repository.py`.
"""

import logging
from typing import Any

from domain.ports.address_repository import AsyncAddressRepository

logger = logging.getLogger(__name__)


async def set_country(
    cur: Any, address_id: int, countries: list[str] | None, *, repo: AsyncAddressRepository
) -> list[int]:
    """Attribue une liste de pays à une adresse.

    - `countries=None` ou `[]` → remet la colonne à NULL.
    - Propage la même valeur aux adresses partageant le même normalized_text.

    Retourne la liste des IDs affectés (y compris address_id).
    Ne valide pas les codes pays : c'est au caller de le faire.
    """
    await repo.set_countries(address_id, countries)
    affected = [address_id]
    if countries:
        affected.extend(await repo.propagate_countries_to_similar_address(address_id))
    return affected


async def batch_set_country_by_ids(
    cur: Any, country_code: str, address_ids: list[int], *, repo: AsyncAddressRepository
) -> list[int]:
    """Ajoute `country_code` à `addresses.countries` pour la liste d'IDs donnée.

    - Si `countries` est NULL → le crée à [country_code].
    - Si `country_code` est déjà dans `countries` → no-op.
    - Sinon → append.

    Retourne les IDs effectivement modifiés (= tous ceux passés en entrée).
    """
    return await repo.batch_add_country_by_ids(country_code, address_ids)


async def batch_set_country_by_filter(
    cur: Any,
    country_code: str,
    *,
    search: str | None = None,
    has_country: str | None = None,
    country_code_filter: str | None = None,
    suggested_country: str | None = None,
    repo: AsyncAddressRepository,
) -> list[int]:
    """Ajoute `country_code` à toutes les adresses correspondant aux filtres.

    Filtres combinés en AND (tous doivent matcher). Si aucun filtre n'est
    fourni, applique à TOUTES les adresses (use with caution).

    Retourne les IDs modifiés.
    """
    conditions: list[str] = []
    params: list = []
    if search:
        conditions.append("unaccent(raw_text) ILIKE unaccent(%s)")
        params.append(f"%{search}%")
    if has_country == "yes":
        conditions.append("countries IS NOT NULL")
    elif has_country == "no":
        conditions.append("countries IS NULL")
    if country_code_filter:
        conditions.append("%s = ANY(countries)")
        params.append(country_code_filter)
    if suggested_country:
        conditions.append("%s = ANY(suggested_countries)")
        params.append(suggested_country)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    return await repo.batch_add_country_by_where(
        country_code,
        where_clause,
        params,
    )


async def propagate_countries_to_similar(cur: Any, *, repo: AsyncAddressRepository) -> list[int]:
    """Propage addresses.countries vers toutes les adresses partageant le même
    normalized_text, quand l'autre adresse a des countries différents.

    Appelée après un batch_set_country_by_* pour propager à travers tout le
    référentiel d'adresses. Retourne les IDs propagés.
    """
    return await repo.propagate_countries_across_similar_addresses()


async def propagate_countries_to_publications(
    cur: Any, address_ids: list[int], *, repo: AsyncAddressRepository
) -> None:
    """Propage addresses.countries → source_publications.countries → publications.countries.

    Appelée après une modification de pays sur les adresses (typiquement en
    background task). Recalcule par agrégation, idempotent.
    """
    if not address_ids:
        return

    addr_docs = await repo.refresh_source_publications_countries(address_ids)
    pubs = await repo.refresh_publications_countries_for_addresses(address_ids)

    if addr_docs or pubs:
        logger.info(f"Propagation pays : {addr_docs} docs source, {pubs} publications")
