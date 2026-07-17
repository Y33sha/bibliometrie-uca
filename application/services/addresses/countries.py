"""Pays des adresses — attribution manuelle, propagation horizontale (adresses jumelles) et verticale (vers `source_publications` / `publications`)."""

import logging

from application.ports.repositories.address_repository import (
    AddressCountryFilter,
    AddressRepository,
)
from domain.errors import ValidationError

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
    Ne valide pas les codes pays : c'est à l'appelant de le faire.
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


def _has_country_flag(value: str | None) -> bool | None:
    """Booléen tri-état du filtre `has_country` : "yes" → True, "no" → False, autre → None."""
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def batch_set_country_by_filter(
    country_code: str,
    *,
    search: str | None = None,
    has_country: str | None = None,
    country_code_filter: str | None = None,
    suggested_country: str | None = None,
    repo: AddressRepository,
) -> list[int]:
    """Ajoute `country_code` aux adresses correspondant aux filtres.

    Filtres combinés en AND (tous doivent correspondre). **Au moins un filtre est exigé** : un appel sans aucun filtre est refusé (`ValidationError`), garde-fou contre l'application d'un pays à toutes les adresses en masse (~475k → cascade de propagation). Pour viser un grand ensemble explicitement, passer par `batch_set_country_by_ids`.

    Retourne les IDs modifiés.
    """
    criteria = AddressCountryFilter(
        search=search,
        has_country=_has_country_flag(has_country),
        country_code=country_code_filter,
        suggested_country=suggested_country,
    )
    if criteria.is_empty:
        raise ValidationError(
            "batch_set_country_by_filter exige au moins un filtre "
            "(search / has_country / country_code_filter / suggested_country) : "
            "refus d'appliquer un pays à toutes les adresses."
        )
    return repo.batch_add_country_by_filter(country_code, criteria)


def propagate_countries_to_similar(
    *, modified_ids: list[int], repo: AddressRepository
) -> list[int]:
    """Propage les `countries` des adresses `modified_ids` vers leurs jumelles (même `normalized_text`).

    Appelée après un `batch_set_country_by_*` pour propager les modifications fraîches aux adresses similaires. Cible explicitement les sources de propagation pour rester sub-seconde (vs un balayage global O(n²) sur les ~475k adresses sans index btree sur `normalized_text`).
    """
    return repo.propagate_countries_across_similar_addresses(modified_ids)


def propagate_countries_to_publications(address_ids: list[int], *, repo: AddressRepository) -> None:
    """Propage addresses.countries → source_publications.countries → publications.countries.

    Appelée après une modification de pays sur les adresses (typiquement en tâche de fond). Recalcule depuis les adresses, idempotent.
    """
    if not address_ids:
        return

    docs = repo.refresh_source_publications_countries(address_ids)
    pubs = repo.refresh_publications_countries_for_addresses(address_ids)

    if docs or pubs:
        logger.info(f"Propagation pays : {docs} docs source, {pubs} publications")
