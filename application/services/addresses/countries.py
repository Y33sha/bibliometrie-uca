"""Pays des adresses — attribution manuelle, propagation horizontale (adresses jumelles) et verticale (vers `source_publications` / `publications`).

Les opérations ensemblistes (ajout par lot, propagations) passent par le gateway `CountryQueries` ; le référentiel (`country_exists`) et l'écriture unitaire d'une adresse (`set_countries`) restent sur `AddressRepository`.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.countries import AddressCountryFilter, CountryQueries
from application.ports.repositories.address_repository import AddressRepository
from domain.errors import ValidationError

logger = logging.getLogger(__name__)


def _require_known_countries(codes: list[str], *, repo: AddressRepository) -> None:
    """Refuse un code absent du référentiel `countries`, qu'aucune clé étrangère ne garde côté tableau."""
    for code in codes:
        if not repo.country_exists(code):
            raise ValidationError(f"Code pays inconnu : {code}")


def set_country(
    conn: Connection,
    address_id: int,
    countries: list[str] | None,
    *,
    repo: AddressRepository,
    country_queries: CountryQueries,
) -> list[int]:
    """Attribue une liste de pays à une adresse.

    - `countries=None` ou `[]` → remet la colonne à NULL.
    - Propage la même valeur aux adresses partageant le même normalized_text.

    Retourne la liste des IDs affectés (y compris address_id). Lève `ValidationError` sur un code absent du référentiel, `NotFoundError` sur une adresse introuvable.
    """
    _require_known_countries(countries or [], repo=repo)
    repo.set_countries(address_id, countries)
    affected = [address_id]
    if countries:
        affected.extend(
            country_queries.propagate_countries_across_similar_addresses(conn, [address_id])
        )
    return affected


def batch_set_country_by_ids(
    conn: Connection,
    country_code: str,
    address_ids: list[int],
    *,
    repo: AddressRepository,
    country_queries: CountryQueries,
) -> list[int]:
    """Ajoute `country_code` à `addresses.countries` pour la liste d'IDs donnée.

    - Si `countries` est NULL → le crée à [country_code].
    - Si `country_code` est déjà dans `countries` → no-op.
    - Sinon → append.

    Retourne les IDs effectivement modifiés (= tous ceux passés en entrée). Lève `ValidationError` sur un code absent du référentiel.
    """
    _require_known_countries([country_code], repo=repo)
    return country_queries.batch_add_country_by_ids(conn, country_code, address_ids)


def batch_set_country_by_filter(
    conn: Connection,
    country_code: str,
    *,
    search: str | None = None,
    has_country: bool | None = None,
    country_code_filter: str | None = None,
    suggested_country: str | None = None,
    repo: AddressRepository,
    country_queries: CountryQueries,
) -> list[int]:
    """Ajoute `country_code` aux adresses correspondant aux filtres.

    Filtres combinés en AND (tous doivent correspondre). **Au moins un filtre est exigé** : un appel sans aucun filtre est refusé (`ValidationError`), garde-fou contre l'application d'un pays à toutes les adresses en masse (~475k → cascade de propagation). Pour viser un grand ensemble explicitement, passer par `batch_set_country_by_ids`.

    Retourne les IDs modifiés. Lève `ValidationError` sur un code absent du référentiel.
    """
    _require_known_countries([country_code], repo=repo)
    criteria = AddressCountryFilter(
        search=search,
        has_country=has_country,
        country_code=country_code_filter,
        suggested_country=suggested_country,
    )
    if criteria.is_empty:
        raise ValidationError(
            "batch_set_country_by_filter exige au moins un filtre "
            "(search / has_country / country_code_filter / suggested_country) : "
            "refus d'appliquer un pays à toutes les adresses."
        )
    return country_queries.batch_add_country_by_filter(conn, country_code, criteria)


def propagate_countries_to_similar(
    conn: Connection, *, modified_ids: list[int], country_queries: CountryQueries
) -> list[int]:
    """Propage les `countries` des adresses `modified_ids` vers leurs jumelles (même `normalized_text`).

    Appelée après un `batch_set_country_by_*` pour propager les modifications fraîches aux adresses similaires. Cible explicitement les sources de propagation pour rester sub-seconde (vs un balayage global O(n²) sur les ~475k adresses sans index btree sur `normalized_text`).
    """
    return country_queries.propagate_countries_across_similar_addresses(conn, modified_ids)


def propagate_countries_to_publications(
    conn: Connection, address_ids: list[int], *, country_queries: CountryQueries
) -> None:
    """Propage addresses.countries → source_publications.countries → publications.countries.

    Appelée après une modification de pays sur les adresses (typiquement en tâche de fond). Recalcule depuis les adresses, idempotent.
    """
    if not address_ids:
        return

    docs = country_queries.refresh_source_publications_countries_for_addresses(conn, address_ids)
    pubs = country_queries.refresh_publications_countries_for_addresses(conn, address_ids)

    if docs or pubs:
        logger.info("Propagation pays : %s docs source, %s publications", docs, pubs)
