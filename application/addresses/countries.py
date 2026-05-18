"""
Service Pays des adresses — attribution, propagation horizontale
(adresses similaires) et verticale (vers source_publications /
publications).

Séparé de `application/addresses.py` (principe SRP) : la validation
des liens adresse↔structure vit dans
`application/addresses_structures.py`. Les deux surfaces partagent
l'agrégat Address mais n'interagissent pas entre elles.
"""

import logging

from application.ports.repositories.address_repository import AddressRepository

logger = logging.getLogger(__name__)


def set_country(
    address_id: int,
    countries: list[str] | None,
    *,
    repo: AddressRepository,
) -> list[int]:
    """Attribue une liste de pays à une adresse.

    - `countries=None` ou `[]` → remet la colonne à NULL.
    - Propage la même valeur aux adresses partageant le même normalized_text.

    Retourne la liste des IDs affectés (y compris address_id).
    Ne valide pas les codes pays : c'est au caller de le faire.
    """
    repo.set_countries(address_id, countries)
    affected = [address_id]
    if countries:
        affected.extend(repo.propagate_countries_across_similar_addresses([address_id]))
    return affected


def batch_set_country_by_ids(
    country_code: str,
    address_ids: list[int],
    *,
    repo: AddressRepository,
) -> list[int]:
    """Ajoute `country_code` à `addresses.countries` pour la liste d'IDs donnée.

    - Si `countries` est NULL → le crée à [country_code].
    - Si `country_code` est déjà dans `countries` → no-op.
    - Sinon → append.

    Retourne les IDs effectivement modifiés (= tous ceux passés en entrée).
    """
    return repo.batch_add_country_by_ids(country_code, address_ids)


def batch_set_country_by_filter(
    country_code: str,
    *,
    search: str | None = None,
    has_country: str | None = None,
    country_code_filter: str | None = None,
    suggested_country: str | None = None,
    repo: AddressRepository,
) -> list[int]:
    """Ajoute `country_code` à toutes les adresses correspondant aux filtres.

    Filtres combinés en AND (tous doivent matcher). Si aucun filtre n'est
    fourni, applique à TOUTES les adresses (use with caution).

    Retourne les IDs modifiés.
    """
    conditions: list[str] = []
    params: list[object] = []
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
    return repo.batch_add_country_by_where(
        country_code,
        where_clause,
        params,
    )


def propagate_countries_to_similar(
    *, modified_ids: list[int], repo: AddressRepository
) -> list[int]:
    """Propage les `countries` des adresses `modified_ids` vers leurs jumelles (même `normalized_text`).

    Appelée après un `batch_set_country_by_*` pour propager les modifications fraîches aux adresses similaires. Cible explicitement les sources de propagation pour rester sub-seconde (vs un balayage global O(n²) sur les ~475k adresses sans index btree sur `normalized_text`).
    """
    return repo.propagate_countries_across_similar_addresses(modified_ids)


def propagate_countries_to_publications(address_ids: list[int], *, repo: AddressRepository) -> None:
    """Propage addresses.countries → sa.countries → sp.countries → publications.countries.

    Appelée après une modification de pays sur les adresses (typiquement en
    background task). Recalcule en cascade, idempotent.
    """
    if not address_ids:
        return

    sa_count = repo.refresh_sa_countries_for_addresses(address_ids)
    addr_docs = repo.refresh_source_publications_countries(address_ids)
    pubs = repo.refresh_publications_countries_for_addresses(address_ids)

    if sa_count or addr_docs or pubs:
        logger.info(
            f"Propagation pays : {sa_count} authorships, {addr_docs} docs source, "
            f"{pubs} publications"
        )
