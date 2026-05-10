"""SQL pour `person_identifiers` (ORCID, idHAL, IdRef...)."""

from sqlalchemy import Connection, text

from domain.errors import NotFoundError


def add_identifier(
    conn: Connection,
    person_id: int,
    id_type: str,
    id_value: str,
    source: str = "auto",
    status: str = "pending",
) -> None:
    """Ajoute un identifiant à une personne.

    Si l'identifiant existe avec statut 'rejected', le réattribue
    (nouveau person_id, statut pending). Si 'pending' ou 'confirmed',
    ne fait rien.

    Pour les idHAL, rattache aussi le compte HAL correspondant dans
    `source_persons` (side-effect cross-table attendu par le pipeline).
    """
    conn.execute(
        text("""
            INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
            VALUES (:pid, :it, :iv, :src, CAST(:st AS identifier_status))
            ON CONFLICT (id_type, id_value) DO UPDATE SET
                person_id = EXCLUDED.person_id,
                source = EXCLUDED.source,
                status = 'pending'
            WHERE person_identifiers.status = 'rejected'
        """),
        {"pid": person_id, "it": id_type, "iv": id_value, "src": source, "st": status},
    )
    if id_type == "idhal":
        conn.execute(
            text("""
                UPDATE source_persons SET person_id = :pid
                WHERE source = 'hal'
                  AND source_ids->>'idhal' = :iv
                  AND (person_id IS NULL OR person_id != :pid)
            """),
            {"pid": person_id, "iv": id_value},
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


def update_identifier_status(conn: Connection, ident_id: int, status: str) -> dict:
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
    return dict(row._mapping)


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
