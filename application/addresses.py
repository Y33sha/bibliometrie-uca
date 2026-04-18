"""
Service Addresses — orchestrateur des opérations sur `addresses`,
`address_structures`, et propagation des pays vers les publications.

Le SQL vit dans `infrastructure/repositories/address_repository.py`.
Les routers passent par ces fonctions pour toute écriture sur les
adresses. Les lectures restent autorisées dans les routers (convention
du projet).
"""

import logging

from infrastructure.repositories.address_repository import PgAddressRepository
from application.authorships import propagate_uca_for_addresses

logger = logging.getLogger(__name__)


# ── Validation des liens adresse ↔ structure ──────────────────────


def review_structure_link(cur, address_id: int, structure_id: int,
                           is_confirmed: bool | None) -> None:
    """Upsert le lien address ↔ structure (validation manuelle).

    - is_confirmed = True  → confirme (crée le lien si besoin)
    - is_confirmed = False → rejette (crée le lien si besoin)
    - is_confirmed = None  → reset (supprime le lien manuel, remet l'auto à NULL)

    Propage automatiquement l'UCA aux source_authorships et authorships vérité.
    """
    repo = PgAddressRepository(cur)
    if is_confirmed is None:
        repo.reset_manual_link(address_id, structure_id)
    else:
        repo.upsert_structure_link(address_id, structure_id, is_confirmed)
    propagate_uca_for_addresses(cur, [address_id])


def batch_review_structure_link(cur, address_ids: list[int], structure_id: int,
                                 is_confirmed: bool | None) -> int:
    """Comme review_structure_link mais sur un lot d'adresses.

    Retourne le nombre d'adresses touchées (pour les reset, nombre de lignes
    UPDATEes ; pour les upserts, taille du lot passé).
    """
    if not address_ids:
        return 0

    repo = PgAddressRepository(cur)
    if is_confirmed is None:
        updated = repo.batch_reset_manual_links(address_ids, structure_id)
    else:
        repo.batch_upsert_structure_links(address_ids, structure_id, is_confirmed)
        updated = len(address_ids)

    propagate_uca_for_addresses(cur, address_ids)
    return updated


def unassign_manual_structure(cur, address_id: int, structure_id: int) -> bool:
    """Supprime uniquement le lien manuel (matched_form_id IS NULL) entre
    une adresse et une structure. Les liens auto-détectés et leurs is_confirmed
    ne sont pas touchés (contrairement à review_structure_link(None)).

    Propage automatiquement l'UCA.
    Retourne True si un lien manuel a été supprimé, False sinon.
    """
    deleted = PgAddressRepository(cur).delete_manual_structure_link(address_id, structure_id)
    propagate_uca_for_addresses(cur, [address_id])
    return deleted


# ── Attribution des pays ──────────────────────────────────────────


def set_country(cur, address_id: int, countries: list[str] | None) -> list[int]:
    """Attribue une liste de pays à une adresse.

    - `countries=None` ou `[]` → remet la colonne à NULL.
    - Propage la même valeur aux adresses partageant le même normalized_text.

    Retourne la liste des IDs affectés (y compris address_id).
    Ne valide pas les codes pays : c'est au caller de le faire.
    """
    repo = PgAddressRepository(cur)
    repo.set_countries(address_id, countries)
    affected = [address_id]
    if countries:
        affected.extend(repo.propagate_countries_to_similar_address(address_id))
    return affected


def batch_set_country_by_ids(cur, country_code: str, address_ids: list[int]) -> list[int]:
    """Ajoute `country_code` à `addresses.countries` pour la liste d'IDs donnée.

    - Si `countries` est NULL → le crée à [country_code].
    - Si `country_code` est déjà dans `countries` → no-op.
    - Sinon → append.

    Retourne les IDs effectivement modifiés (= tous ceux passés en entrée).
    """
    return PgAddressRepository(cur).batch_add_country_by_ids(country_code, address_ids)


def batch_set_country_by_filter(
    cur,
    country_code: str,
    *,
    search: str | None = None,
    has_country: str | None = None,
    country_code_filter: str | None = None,
    suggested_country: str | None = None,
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
    return PgAddressRepository(cur).batch_add_country_by_where(
        country_code, where_clause, params,
    )


def propagate_countries_to_similar(cur) -> list[int]:
    """Propage addresses.countries vers toutes les adresses partageant le même
    normalized_text, quand l'autre adresse a des countries différents.

    Appelée après un batch_set_country_by_* pour propager à travers tout le
    référentiel d'adresses. Retourne les IDs propagés.
    """
    return PgAddressRepository(cur).propagate_countries_across_similar_addresses()


# ── Propagation pays vers source_publications et publications ────


def propagate_countries_to_publications(cur, address_ids: list[int]) -> None:
    """Propage addresses.countries → source_publications.countries → publications.countries.

    Appelée après une modification de pays sur les adresses (typiquement en
    background task). Recalcule par agrégation, idempotent.
    """
    if not address_ids:
        return

    repo = PgAddressRepository(cur)
    addr_docs = repo.refresh_source_publications_countries(address_ids)
    pubs = repo.refresh_publications_countries_for_addresses(address_ids)

    if addr_docs or pubs:
        logger.info(f"Propagation pays : {addr_docs} docs source, {pubs} publications")
