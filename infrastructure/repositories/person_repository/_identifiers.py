"""SQL pour `person_identifiers` (ORCID, idHAL, IdRef...)."""

from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.person_repository import (
    AuthenticateOrcidOutcome,
    IdentifierStatusRow,
)
from domain.errors import NotFoundError
from domain.persons.identifier_attribution import IdentifierAttribution
from domain.persons.identifiers import AttributionStatus, IdentifierOrigin, PersonIdentifierType
from infrastructure.db.scalars import row_int
from infrastructure.db.sql_fragments import identifier_neutralized


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


def find_identifier_holders(
    conn: Connection, id_type: str, id_values: list[str]
) -> dict[str, tuple[int, str]]:
    """Pour chaque valeur de `id_values` déjà présente sous ce type : `{id_value: (person_id, statut)}` de son porteur actuel. Sert à prévoir les déplacements avant l'import des ORCID authentifiés."""
    return {
        r.id_value: (r.person_id, r.status)
        for r in conn.execute(
            text(
                "SELECT id_value, person_id, CAST(status AS text) AS status "
                "FROM person_identifiers WHERE id_type = :it AND id_value = ANY(:v)"
            ),
            {"it": id_type, "v": id_values},
        )
    }


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


def propagate_status_to_hal_accounts(conn: Connection, ident_id: int, status: str) -> int:
    # Comptes HAL : `hal_person_id` des signatures HAL de la personne qui portent l'identifiant.
    # Groupe : identifiants que portent les signatures HAL de la personne sous ces comptes.
    # Un identifiant neutralisé par sa signature n'entre ni dans l'un ni dans l'autre.
    return conn.execute(
        text(f"""
            WITH src AS (
                SELECT person_id, id_type, id_value
                FROM person_identifiers WHERE id = :id
            ),
            hal_identities AS (
                SELECT sa.neutralized_identifiers, aik.person_identifiers
                FROM src
                JOIN source_authorships sa ON sa.person_id = src.person_id AND sa.source = 'hal'
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE aik.person_identifiers ? '{PersonIdentifierType.HAL_PERSON_ID.value}'
            ),
            accounts AS (
                SELECT DISTINCT person_identifiers->>'{PersonIdentifierType.HAL_PERSON_ID.value}' AS hal
                FROM hal_identities sa, src
                WHERE person_identifiers->>src.id_type = src.id_value
                  AND NOT {identifier_neutralized("src.id_type")}
            ),
            bundle AS (
                SELECT DISTINCT k.id_type, sa.person_identifiers->>k.id_type AS id_value
                FROM hal_identities sa
                JOIN accounts
                  ON sa.person_identifiers->>'{PersonIdentifierType.HAL_PERSON_ID.value}' = accounts.hal
                CROSS JOIN LATERAL jsonb_object_keys(sa.person_identifiers) AS k(id_type)
                WHERE NOT {identifier_neutralized("k.id_type")}
            )
            UPDATE person_identifiers pi
            SET status = CAST(:st AS identifier_status)
            FROM src, bundle
            WHERE pi.person_id = src.person_id
              AND pi.id_type = bundle.id_type
              AND pi.id_value = bundle.id_value
              AND pi.status = '{AttributionStatus.PENDING.value}'
              AND pi.id <> :id
        """),
        {"id": ident_id, "st": status},
    ).rowcount


def begin_authenticated_orcid_import(conn: Connection) -> None:
    """Pose le paramètre de session lu par le trigger `protect_authenticated_identifier`. `SET LOCAL` : l'effet est borné à la transaction et disparaît au commit/rollback."""
    conn.execute(text("SET LOCAL app.orcid_authenticated_import = 'on'"))


def authenticate_orcid(conn: Connection, person_id: int, orcid: str) -> AuthenticateOrcidOutcome:
    existing = conn.execute(
        text(
            "SELECT id, person_id, CAST(status AS text) AS status "
            "FROM person_identifiers WHERE id_type = 'orcid' AND id_value = :v"
        ),
        {"v": orcid},
    ).first()
    if existing is None:
        conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:pid, 'orcid', :v, :src, 'authenticated')"
            ),
            {"pid": person_id, "v": orcid, "src": IdentifierOrigin.MANUAL.value},
        )
        return AuthenticateOrcidOutcome.INSERTED
    if existing.person_id == person_id and existing.status == "authenticated":
        return AuthenticateOrcidOutcome.NOOP
    outcome = (
        AuthenticateOrcidOutcome.REASSIGNED
        if existing.person_id != person_id
        else AuthenticateOrcidOutcome.UPGRADED
    )
    conn.execute(
        text(
            "UPDATE person_identifiers "
            "SET person_id = :pid, status = 'authenticated', source = :src "
            "WHERE id = :id"
        ),
        {"pid": person_id, "id": existing.id, "src": IdentifierOrigin.MANUAL.value},
    )
    return outcome


def reassign_identifier(conn: Connection, ident_id: int, target_person_id: int) -> None:
    result = conn.execute(
        text(
            "UPDATE person_identifiers "
            "SET person_id = :pid, status = CAST('pending' AS identifier_status) "
            "WHERE id = :id"
        ),
        {"pid": target_person_id, "id": ident_id},
    )
    if result.rowcount == 0:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
