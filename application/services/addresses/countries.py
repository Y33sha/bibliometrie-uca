"""Pays des adresses — saisie manuelle, résolution, propagation vers `source_publications` et `publications`.

Une saisie manuelle s'écrit en candidats `manual` par `AddressRepository`, qui l'emportent sur les autres moyens. La résolution de `addresses.countries` et le recalcul des pays des notices et des publications appartiennent au pipeline, qui les expose par `CountryRecompute`.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.countries import CountryRecompute
from application.ports.repositories.address_repository import (
    AddressCountryFilter,
    AddressRepository,
)
from domain.errors import ValidationError

logger = logging.getLogger(__name__)


def _require_known_countries(codes: list[str], *, repo: AddressRepository) -> None:
    """Refuse un code absent du référentiel `countries`."""
    for code in codes:
        if not repo.country_exists(code):
            raise ValidationError(f"Code pays inconnu : {code}")


def set_country(
    conn: Connection,
    address_id: int,
    countries: list[str] | None,
    *,
    repo: AddressRepository,
    country_recompute: CountryRecompute,
) -> list[int]:
    """Saisit à la main les pays d'une adresse, puis résout l'adresse. `countries=None` ou `[]` rend l'adresse aux moyens automatiques.

    Retourne `[address_id]`. Lève `ValidationError` sur un code absent du référentiel, `NotFoundError` sur une adresse introuvable.
    """
    _require_known_countries(countries or [], repo=repo)
    repo.set_manual_countries(address_id, countries)
    country_recompute.resolve_address_countries(conn, [address_id])
    return [address_id]


def batch_set_country_by_ids(
    conn: Connection,
    country_code: str,
    address_ids: list[int],
    *,
    repo: AddressRepository,
    country_recompute: CountryRecompute,
) -> list[int]:
    """Ajoute `country_code` aux pays des adresses données : leurs pays retenus et `country_code` deviennent leurs pays saisis à la main. Résout ensuite les adresses.

    Retourne les IDs atteints. Lève `ValidationError` sur un code absent du référentiel.
    """
    _require_known_countries([country_code], repo=repo)
    ids = repo.add_manual_country_by_ids(country_code, address_ids)
    country_recompute.resolve_address_countries(conn, ids)
    return ids


def batch_set_country_by_filter(
    conn: Connection,
    country_code: str,
    *,
    search: str | None = None,
    has_country: bool | None = None,
    country_code_filter: str | None = None,
    proposed_country: str | None = None,
    repo: AddressRepository,
    country_recompute: CountryRecompute,
) -> list[int]:
    """Ajoute `country_code` aux pays des adresses correspondant aux filtres, comme `batch_set_country_by_ids`.

    Filtres combinés en AND (tous doivent correspondre). **Au moins un filtre est exigé** : un appel sans aucun filtre est refusé (`ValidationError`), garde-fou contre l'application d'un pays à toutes les adresses en masse (~475k → cascade de propagation). Pour viser un grand ensemble explicitement, passer par `batch_set_country_by_ids`.

    Retourne les IDs modifiés. Lève `ValidationError` sur un code absent du référentiel.
    """
    _require_known_countries([country_code], repo=repo)
    criteria = AddressCountryFilter(
        search=search,
        has_country=has_country,
        country_code=country_code_filter,
        proposed_country=proposed_country,
    )
    if criteria.is_empty:
        raise ValidationError(
            "batch_set_country_by_filter exige au moins un filtre "
            "(search / has_country / country_code_filter / proposed_country) : "
            "refus d'appliquer un pays à toutes les adresses."
        )
    ids = repo.add_manual_country_by_filter(country_code, criteria)
    country_recompute.resolve_address_countries(conn, ids)
    return ids


def propagate_countries_to_publications(
    conn: Connection, address_ids: list[int], *, country_recompute: CountryRecompute
) -> None:
    """Propage addresses.countries → source_publications.countries → publications.countries.

    Appelée après une modification de pays sur les adresses (typiquement en tâche de fond). Recalcule depuis les adresses, idempotent.
    """
    if not address_ids:
        return

    docs = country_recompute.refresh_source_publications_countries_for_addresses(conn, address_ids)
    pubs = country_recompute.refresh_publications_countries_for_addresses(conn, address_ids)

    if docs or pubs:
        logger.info("Propagation pays : %s docs source, %s publications", docs, pubs)
