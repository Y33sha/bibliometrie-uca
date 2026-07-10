"""Command handlers des écritures API sur les adresses : la frontière transactionnelle.

Une écriture API est une commande (intention courte d'un acteur). Chaque command
handler reçoit la connexion de la requête et les ports (repos), compose les
briques d'écriture agnostiques de `structures.py` / `countries.py`, et
`conn.commit()` au succès — pour que la donnée soit persistée avant l'envoi de la
réponse et avant les tâches de fond (cf.
`docs/chantiers/CODE_commit-avant-reponse.md`). Les briques composées restent
transaction-agnostiques (réutilisées par le pipeline et les CLI) ; seul le
command handler commit.

Les propagations potentiellement massives (`in_perimeter`, pays → publications)
ne sont pas faites ici : le handler retourne les identifiants d'adresses
concernés, que le routeur passe en tâche de fond (elles lisent l'état committé
puisque le commit précède leur exécution).
"""

from sqlalchemy import Connection

from application.ports.repositories.address_repository import AddressRepository
from application.services.addresses import (
    countries as countries_service,
    structures as structures_service,
)


def review_structure_link(
    conn: Connection,
    address_id: int,
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AddressRepository,
) -> list[int]:
    """Valide un lien adresse ↔ structure. Retourne les adresses dont la
    contribution à `in_perimeter` a changé (à propager en tâche de fond)."""
    changed = structures_service.review_structure_link(
        address_id, structure_id, is_confirmed, repo=repo
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
) -> tuple[int, list[int]]:
    """Valide un lot de liens adresse ↔ structure. Retourne `(nombre d'adresses
    touchées, adresses dont la contribution à `in_perimeter` a changé)`."""
    updated, changed = structures_service.batch_review_structure_link(
        address_ids, structure_id, is_confirmed, repo=repo
    )
    conn.commit()
    return updated, changed


def set_country(
    conn: Connection,
    address_id: int,
    countries: list[str] | None,
    *,
    repo: AddressRepository,
) -> list[int]:
    """Attribue des pays à une adresse. Retourne les adresses affectées (l'adresse
    et ses jumelles), à propager vers les publications en tâche de fond."""
    affected = countries_service.set_country(address_id, countries, repo=repo)
    conn.commit()
    return affected


def batch_set_country(
    conn: Connection,
    country_code: str,
    *,
    address_ids: list[int] | None,
    search: str,
    has_country: str,
    country_code_filter: str,
    suggested_country: str,
    repo: AddressRepository,
) -> tuple[int, int, list[int]]:
    """Ajoute un pays à des adresses (par identifiants ou par filtre), puis le
    propage aux adresses jumelles, en une seule transaction.

    Retourne `(adresses modifiées, adresses propagées, tous les identifiants
    concernés)` ; le dernier est à propager vers les publications en tâche de fond.
    """
    if address_ids:
        modified_ids = countries_service.batch_set_country_by_ids(
            country_code, address_ids, repo=repo
        )
    else:
        modified_ids = countries_service.batch_set_country_by_filter(
            country_code,
            search=search,
            has_country=has_country,
            country_code_filter=country_code_filter,
            suggested_country=suggested_country,
            repo=repo,
        )
    propagated_ids = countries_service.propagate_countries_to_similar(
        modified_ids=modified_ids, repo=repo
    )
    conn.commit()
    return len(modified_ids), len(propagated_ids), modified_ids + propagated_ids
