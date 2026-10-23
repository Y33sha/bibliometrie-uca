"""Adapter PostgreSQL sync pour le cluster `addresses` : liens adresse ↔ structure, pays saisis à la main (candidats `manual`, unitairement ou par lot).

La résolution des pays d'une adresse et le recalcul des pays des enregistrements sources et des publications appartiennent au pipeline (`pipeline/transformation/countries/`). Chaque saisie met l'adresse dans la file `address_candidates_queue` : le run suivant résout l'adresse si la résolution immédiate a échoué.
"""

from sqlalchemy import Connection, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.address_repository import (
    AddressCountryFilter,
    AddressRepository,
)
from domain.country_detection import CountryDetectionMethod
from domain.errors import NotFoundError
from infrastructure.db.queues import Queue, enqueue, enqueue_sql
from infrastructure.db.tables import (
    address_country_candidates,
    address_structures,
    countries,
)
from infrastructure.sql_fragments import address_country_conditions

# Marque les adresses de la CTE `target(id, countries)`.
_MARK_TARGET = enqueue_sql(Queue.ADDRESS_CANDIDATES, "SELECT id FROM target")


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

        Condition miroir du lien adresse → structure de la matview `source_contribution_structures`, à garder synchronisée.
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

    def set_manual_countries(self, address_id: int, countries: list[str] | None) -> None:
        marked = enqueue(
            self._conn,
            Queue.ADDRESS_CANDIDATES,
            "SELECT id FROM addresses WHERE id = :id",
            {"id": address_id},
        )
        if marked == 0:
            raise NotFoundError(f"Adresse {address_id} introuvable")
        self._conn.execute(
            delete(address_country_candidates).where(
                address_country_candidates.c.address_id == address_id,
                address_country_candidates.c.method == CountryDetectionMethod.MANUAL,
            )
        )
        if countries:
            self._conn.execute(
                pg_insert(address_country_candidates).values(
                    [
                        {
                            "address_id": address_id,
                            "country_code": code,
                            "method": CountryDetectionMethod.MANUAL,
                        }
                        for code in dict.fromkeys(countries)
                    ]
                )
            )

    def add_manual_country_by_ids(self, country_code: str, address_ids: list[int]) -> list[int]:
        if not address_ids:
            return []
        result = self._conn.execute(
            text(f"""
                WITH target AS (
                    SELECT id, countries FROM addresses WHERE id = ANY(:ids)
                ), marked AS ({_MARK_TARGET}), added AS (
                    INSERT INTO address_country_candidates (address_id, country_code, method)
                    SELECT DISTINCT t.id, code, 'manual'::country_detection_method
                    FROM target t
                    CROSS JOIN LATERAL unnest(
                        coalesce(t.countries, '{{}}') || ARRAY[CAST(:cc AS char(2))]
                    ) code
                    ON CONFLICT DO NOTHING
                )
                SELECT id FROM target
            """),
            {"cc": country_code, "ids": address_ids},
        )
        return [row.id for row in result]

    def add_manual_country_by_filter(
        self, country_code: str, criteria: AddressCountryFilter
    ) -> list[int]:
        conditions, params = address_country_conditions(criteria)
        if not conditions:
            return []

        ids = list(
            self._conn.execute(
                text(f"SELECT a.id FROM addresses a WHERE {' AND '.join(conditions)}"), params
            ).scalars()
        )
        return self.add_manual_country_by_ids(country_code, ids)
