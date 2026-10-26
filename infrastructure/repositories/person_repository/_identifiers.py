"""SQL pour `person_identifiers` (ORCID, idHAL, IdRef...)."""

from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.person_repository import (
    IdentifierStatusRow,
)
from domain.errors import NotFoundError
from domain.persons.identifier_attribution import IdentifierAttribution
from domain.persons.identifiers import AttributionStatus, IdentifierOrigin, PersonIdentifierType
from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.db.scalars import row_int
from infrastructure.sql_fragments import CONTRIBUTIONS_AND_SOURCES, identifier_neutralized


def find_identifier(conn: Connection, id_type: str, id_value: str) -> IdentifierAttribution | None:
    row = conn.execute(
        text("""
            SELECT id, person_id, id_type, id_value, source, CAST(status AS text) AS status
            FROM person_identifiers
            WHERE id_type = :it AND id_value = :iv
        """),
        {"it": id_type, "iv": id_value},
    ).first()
    if not row:
        return None
    m = row._mapping
    return IdentifierAttribution(
        id=m["id"],
        person_id=m["person_id"],
        id_type=m["id_type"],
        id_value=m["id_value"],
        status=AttributionStatus(m["status"]),
        source=IdentifierOrigin(m["source"]),
    )


def insert_identifier(conn: Connection, ident: IdentifierAttribution) -> int:
    row = conn.execute(
        text("""
            INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
            VALUES (:pid, :it, :iv, :src, CAST(:st AS identifier_status))
            RETURNING id
        """),
        {
            "pid": ident.person_id,
            "it": ident.id_type,
            "iv": ident.id_value,
            "src": ident.source,
            "st": ident.status.value,
        },
    ).first()
    assert row is not None  # RETURNING garantit une ligne
    ident.id = row_int(row.id)
    return ident.id


def update_identifier(conn: Connection, ident: IdentifierAttribution) -> None:
    if ident.id is None:
        raise ValueError("update_identifier : ident.id doit être posé (utiliser insert_identifier)")
    conn.execute(
        text("""
            UPDATE person_identifiers
            SET person_id = :pid,
                status = CAST(:st AS identifier_status),
                source = :src
            WHERE id = :id
        """),
        {
            "id": ident.id,
            "pid": ident.person_id,
            "st": ident.status.value,
            "src": ident.source,
        },
    )


def update_identifier_status(conn: Connection, ident_id: int, status: str) -> IdentifierStatusRow:
    row = conn.execute(
        text(
            "UPDATE person_identifiers SET status = CAST(:st AS identifier_status) "
            "WHERE id = :id RETURNING id, CAST(status AS text) AS status, person_id"
        ),
        {"st": status, "id": ident_id},
    ).first()
    if not row:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
    return cast(IdentifierStatusRow, dict(row._mapping))


_HAL = PersonIdentifierType.HAL_PERSON_ID.value

# Comptes HAL d'un identifiant : `hal_person_id` des contributions sources HAL des contributions de sa personne qui le contiennent.
# Lot : identifiants des contributions sources HAL des contributions de la personne sous ces comptes.
# Un identifiant neutralisé par sa contribution source reste hors de l'un et de l'autre.
_HAL_ACCOUNT_PEERS_SQL = text(f"""
    WITH src AS (
        SELECT id AS src_id, person_id, id_type, id_value
        FROM person_identifiers WHERE id = ANY(:ids)
    ),
    hal_identities AS (
        SELECT DISTINCT g.person_id, sc.neutralized_identifiers, ci.identifiers
        FROM {CONTRIBUTIONS_AND_SOURCES}
        WHERE g.person_id IN (SELECT person_id FROM src)
          AND sc.source = 'hal'
          AND ci.identifiers ? '{_HAL}'
    ),
    accounts AS (
        SELECT DISTINCT src.src_id, src.person_id, sc.identifiers->>'{_HAL}' AS hal
        FROM src
        JOIN hal_identities sc
          ON sc.person_id = src.person_id
         AND sc.identifiers->>src.id_type = src.id_value
        WHERE NOT {identifier_neutralized("src.id_type")}
    ),
    bundle AS (
        SELECT DISTINCT accounts.src_id, accounts.person_id,
               k.id_type, sc.identifiers->>k.id_type AS id_value
        FROM accounts
        JOIN hal_identities sc
          ON sc.person_id = accounts.person_id
         AND sc.identifiers->>'{_HAL}' = accounts.hal
        CROSS JOIN LATERAL jsonb_object_keys(sc.identifiers) AS k(id_type)
        WHERE NOT {identifier_neutralized("k.id_type")}
    )
    SELECT bundle.src_id, pi.id AS peer_id
    FROM bundle
    JOIN person_identifiers pi
      ON pi.person_id = bundle.person_id
     AND pi.id_type = bundle.id_type
     AND pi.id_value = bundle.id_value
    WHERE pi.status = '{AttributionStatus.PENDING.value}'
      AND pi.id <> bundle.src_id
""")


def hal_account_peers(conn: Connection, ident_ids: list[int]) -> dict[int, set[int]]:
    peers: dict[int, set[int]] = {}
    for r in conn.execute(_HAL_ACCOUNT_PEERS_SQL, {"ids": ident_ids}):
        peers.setdefault(r.src_id, set()).add(r.peer_id)
    return peers


def propagate_status_to_hal_accounts(conn: Connection, ident_id: int, status: str) -> int:
    peer_ids = hal_account_peers(conn, [ident_id]).get(ident_id, set())
    if not peer_ids:
        return 0
    return conn.execute(
        text(
            "UPDATE person_identifiers SET status = CAST(:st AS identifier_status) WHERE id = ANY(:ids)"
        ),
        {"st": status, "ids": list(peer_ids)},
    ).rowcount


# Contribution de la personne rattachée par un identifiant rejeté : son mode de résolution est le type de l'identifiant, et l'une de ses contributions sources porte la valeur.
_MARK_CONTRIBUTIONS_OF_REJECTED_IDENTIFIERS_SQL = text(
    enqueue_sql(
        Queue.CONTRIBUTION_RESOLUTION,
        f"""
            SELECT g.id
            FROM {CONTRIBUTIONS_AND_SOURCES}
            JOIN person_identifiers pi
              ON pi.person_id = g.person_id
             AND pi.id_type = CAST(g.resolution_mode AS text)
             AND ci.identifiers ->> pi.id_type = pi.id_value
            WHERE g.person_id = :pid
              AND pi.status = '{AttributionStatus.REJECTED.value}'
        """,
    )
)


def mark_contributions_of_rejected_identifiers(conn: Connection, person_id: int) -> int:
    return conn.execute(
        _MARK_CONTRIBUTIONS_OF_REJECTED_IDENTIFIERS_SQL, {"pid": person_id}
    ).rowcount
