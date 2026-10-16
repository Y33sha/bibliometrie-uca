"""Adapter PostgreSQL sync pour le cluster `addresses` : liens adresse ↔ structure, pays des adresses (attribution unitaire ou par lot, recopie vers les adresses jumelles).

Le recalcul des pays des notices et des publications appartient au pipeline (`pipeline/transformation/structures/countries/countries_queries.py`). Chaque écriture de pays marque l'adresse `countries_dirty` : le run suivant reprend la propagation si le recalcul ciblé a échoué.
"""

from sqlalchemy import Connection, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.address_repository import (
    AddressCountryFilter,
    AddressRepository,
)
from domain.errors import NotFoundError
from infrastructure.db.tables import address_structures, addresses, countries

# Ajout idempotent d'un code pays à `addresses.countries` : ni doublon, ni écrasement des codes déjà posés. Le code à ajouter est lié au paramètre `:cc`.
_ADD_COUNTRY_SET_CLAUSE = """
    SET countries = CASE
        WHEN countries IS NULL THEN ARRAY[:cc]::char(2)[]
        WHEN :cc = ANY(countries) THEN countries
        ELSE array_append(countries, CAST(:cc AS char(2)))
    END,
    countries_dirty = true
"""


class PgAddressRepository(AddressRepository):
    """Accès PostgreSQL sync à l'agrégat Address."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Liens adresse ↔ structure ──────────────────────────────────

    def reset_manual_link(self, address_id: int, structure_id: int) -> None:
        self._conn.execute(
            delete(address_structures)
            .where(address_structures.c.address_id == address_id)
            .where(address_structures.c.structure_id == structure_id)
            .where(address_structures.c.matched_form_id.is_(None))
        )
        self._conn.execute(
            update(address_structures)
            .where(address_structures.c.address_id == address_id)
            .where(address_structures.c.structure_id == structure_id)
            .values(is_confirmed=None)
        )

    def upsert_structure_link(
        self,
        address_id: int,
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        stmt = pg_insert(address_structures).values(
            address_id=address_id,
            structure_id=structure_id,
            is_confirmed=is_confirmed,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["address_id", "structure_id"],
            set_={"is_confirmed": stmt.excluded.is_confirmed},
        )
        self._conn.execute(stmt)

    def batch_reset_manual_links(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> int:
        # Un rattachement est unique par (address_id, structure_id) : une ligne est soit supprimée (purement manuelle), soit repassée à pending — jamais les deux. Les deux compteurs se cumulent (ensembles disjoints).
        deleted = self._conn.execute(
            delete(address_structures)
            .where(address_structures.c.address_id.in_(address_ids))
            .where(address_structures.c.structure_id == structure_id)
            .where(address_structures.c.matched_form_id.is_(None))
        )
        updated = self._conn.execute(
            update(address_structures)
            .where(address_structures.c.address_id.in_(address_ids))
            .where(address_structures.c.structure_id == structure_id)
            .values(is_confirmed=None)
        )
        return deleted.rowcount + updated.rowcount

    def batch_upsert_structure_links(
        self,
        address_ids: list[int],
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        if not address_ids:
            return
        stmt = pg_insert(address_structures)
        stmt = stmt.on_conflict_do_update(
            index_elements=["address_id", "structure_id"],
            set_={"is_confirmed": stmt.excluded.is_confirmed},
        )
        # SQLAlchemy exécute en mode "executemany" si on passe une liste de dicts.
        self._conn.execute(
            stmt,
            [
                {"address_id": aid, "structure_id": structure_id, "is_confirmed": is_confirmed}
                for aid in address_ids
            ],
        )

    def which_contribute_to_perimeter(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> set[int]:
        """Cf. docstring du port.

        Condition miroir du lien adresse → structure de la matview `source_authorship_structures`, à garder synchronisée.
        """
        if not address_ids:
            return set()
        result = self._conn.execute(
            select(address_structures.c.address_id)
            .where(address_structures.c.address_id.in_(address_ids))
            .where(address_structures.c.structure_id == structure_id)
            .where(address_structures.c.is_confirmed.is_distinct_from(False))
        )
        return {row.address_id for row in result}

    # ── Pays ───────────────────────────────────────────────────────

    def country_exists(self, code: str) -> bool:
        row = self._conn.execute(
            select(countries.c.code).where(countries.c.code == code)
        ).one_or_none()
        return row is not None

    def set_countries(
        self,
        address_id: int,
        countries: list[str] | None,
    ) -> None:
        result = self._conn.execute(
            update(addresses)
            .where(addresses.c.id == address_id)
            .values(countries=countries if countries else None, countries_dirty=True)
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Adresse {address_id} introuvable")

    def batch_add_country_by_ids(self, country_code: str, address_ids: list[int]) -> list[int]:
        if not address_ids:
            return []
        result = self._conn.execute(
            text(f"""
                UPDATE addresses
                {_ADD_COUNTRY_SET_CLAUSE}
                WHERE id = ANY(:ids)
                RETURNING id
            """),
            {"cc": country_code, "ids": address_ids},
        )
        return [row.id for row in result]

    def batch_add_country_by_filter(
        self, country_code: str, criteria: AddressCountryFilter
    ) -> list[int]:
        conditions: list[str] = []
        params: dict[str, object] = {"cc": country_code}
        if criteria.search:
            conditions.append("unaccent(raw_text) ILIKE unaccent(:search)")
            params["search"] = f"%{criteria.search}%"
        if criteria.has_country is True:
            conditions.append("countries IS NOT NULL")
        elif criteria.has_country is False:
            conditions.append("countries IS NULL")
        if criteria.country_code:
            conditions.append(":country_code = ANY(countries)")
            params["country_code"] = criteria.country_code
        if criteria.suggested_country:
            conditions.append(":suggested_country = ANY(suggested_countries)")
            params["suggested_country"] = criteria.suggested_country

        if not conditions:
            return []

        where_clause = " AND ".join(conditions)
        result = self._conn.execute(
            text(f"""
                UPDATE addresses
                {_ADD_COUNTRY_SET_CLAUSE}
                WHERE {where_clause}
                RETURNING id
            """),
            params,
        )
        return [row.id for row in result]
