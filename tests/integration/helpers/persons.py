"""Semis de personnes pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection, text


def insert_person(
    conn: Connection,
    last_name: str = "A",
    *,
    first_name: str = "Z",
    exclusion: str | None = None,
) -> int:
    """Insère une personne et renvoie son `id`. Nom et prénom sont normalisés par `normalize_name_form`, comme dans le pipeline."""
    return conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized, exclusion) "
            "VALUES (:last, :first, normalize_name_form(:last), normalize_name_form(:first), "
            "CAST(:exclusion AS person_exclusion)) RETURNING id"
        ),
        {"last": last_name, "first": first_name, "exclusion": exclusion},
    ).scalar_one()
