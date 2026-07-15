"""SQL pour `person_identifiers` (ORCID, idHAL, IdRef...)."""

from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.person_repository import (
    AuthenticateOrcidOutcome,
    IdentifierStatusRow,
)
from domain.errors import NotFoundError
from domain.persons.identifiers import AttributionStatus
from domain.persons.person_identifier import PersonIdentifier


def find_identifier(conn: Connection, id_type: str, id_value: str) -> PersonIdentifier | None:
    """Charge le `PersonIdentifier` pour une paire `(id_type, id_value)`
    (contrainte d'unicité globale de la table). Retourne None si absent.
    """
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
    return PersonIdentifier(
        id=m["id"],
        person_id=m["person_id"],
        id_type=m["id_type"],
        id_value=m["id_value"],
        status=AttributionStatus(m["status"]),
        source=m["source"],
    )


def insert_identifier(conn: Connection, ident: PersonIdentifier) -> int:
    """Insère un nouveau `PersonIdentifier`. Pose `ident.id` au retour
    et le retourne. Lève si une ligne existe déjà pour `(id_type, id_value)`
    (la contrainte d'unicité est gérée applicativement via `find_identifier`
    avant l'insert)."""
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
    ident.id = row.id
    return row.id


def update_identifier(conn: Connection, ident: PersonIdentifier) -> None:
    """Persiste les mutations sur un `PersonIdentifier` existant
    (`person_id`, `status`, `source`). `id_type` et `id_value` sont
    immuables (identité naturelle, jamais modifiée après création)."""
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


def remove_identifier(conn: Connection, person_id: int, id_type: str, id_value: str) -> None:
    result = conn.execute(
        text(
            "DELETE FROM person_identifiers "
            "WHERE person_id = :pid AND id_type = :it AND id_value = :iv"
        ),
        {"pid": person_id, "it": id_type, "iv": id_value},
    )
    if result.rowcount == 0:
        raise NotFoundError("Identifiant introuvable")


def update_identifier_status(conn: Connection, ident_id: int, status: str) -> IdentifierStatusRow:
    """Change le statut d'un identifiant. Retourne {id, status, person_id}."""
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


def begin_authenticated_orcid_import(conn: Connection) -> None:
    """Ouvre, pour la transaction courante, le droit d'écrire le statut `authenticated`.

    Pose le paramètre de session lu par le trigger `protect_authenticated_identifier`.
    À réserver à l'import des ORCID authentifiés — l'unique contexte autorisé à poser ce
    statut. `SET LOCAL` : l'effet est borné à la transaction et disparaît au commit/rollback.
    """
    conn.execute(text("SET LOCAL app.orcid_authenticated_import = 'on'"))


def authenticate_orcid(conn: Connection, person_id: int, orcid: str) -> AuthenticateOrcidOutcome:
    """Pose le statut `authenticated` sur l'ORCID `orcid`, rattaché à `person_id`, et retourne l'issue.

    Requiert `begin_authenticated_orcid_import` dans la même transaction, sinon le trigger rejette l'écriture. Idempotent. `orcid` est supposé déjà normalisé. Un ORCID porté par une autre personne est déplacé, l'authentification faisant autorité sur l'identité.
    """
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
                "VALUES (:pid, 'orcid', :v, 'manual', 'authenticated')"
            ),
            {"pid": person_id, "v": orcid},
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
            "SET person_id = :pid, status = 'authenticated', source = 'manual' "
            "WHERE id = :id"
        ),
        {"pid": person_id, "id": existing.id},
    )
    return outcome


def reassign_identifier(conn: Connection, ident_id: int, target_person_id: int) -> None:
    """Réattribue un identifiant à une autre personne (statut → pending)."""
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
