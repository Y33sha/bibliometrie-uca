"""Semis de personnes, de leurs identifiants, formes de nom, fiches RH et rejets, pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

import datetime

from sqlalchemy import Connection, text

from tests.integration.helpers.rows import insert_row

_NORMALIZERS = ("normalize_name_form", "lower")


def insert_person(
    conn: Connection,
    last_name: str = "A",
    *,
    first_name: str = "Z",
    exclusion: str | None = None,
    normalizer: str = "normalize_name_form",
    last_name_normalized: str | None = None,
    first_name_normalized: str | None = None,
) -> int:
    """Insère une personne et renvoie son `id`.

    Nom et prénom sont normalisés par la fonction SQL `normalizer` : `normalize_name_form`, comme dans le pipeline, ou `lower`. `last_name_normalized` et `first_name_normalized` imposent une valeur.
    """
    assert normalizer in _NORMALIZERS, normalizer
    return conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized, exclusion) "
            f"VALUES (:last, :first, COALESCE(:last_normalized, {normalizer}(:last)), "
            f"COALESCE(:first_normalized, {normalizer}(:first)), "
            "CAST(:exclusion AS person_exclusion)) RETURNING id"
        ),
        {
            "last": last_name,
            "first": first_name,
            "last_normalized": last_name_normalized,
            "first_normalized": first_name_normalized,
            "exclusion": exclusion,
        },
    ).scalar_one()


def insert_person_identifier(
    conn: Connection,
    person_id: int,
    *,
    id_type: str,
    id_value: str,
    source: str = "auto",
    status: str | None = None,
) -> int:
    """Insère un identifiant de la personne `person_id` et renvoie son `id`. Le statut par défaut est celui du schéma."""
    return insert_row(
        conn,
        "person_identifiers",
        {
            "person_id": person_id,
            "id_type": id_type,
            "id_value": id_value,
            "source": source,
            "status": status,
        },
        {"source": "identifier_origin", "status": "identifier_status"},
    )


def insert_person_name_form(
    conn: Connection,
    person_id: int,
    *,
    name_form: str,
    sources: list[str] | None = None,
    status: str | None = None,
    ignore_conflict: bool = False,
) -> None:
    """Insère une forme de nom de la personne `person_id`. Sources et statut par défaut sont ceux du schéma ; `ignore_conflict` ignore une forme déjà présente."""
    insert_row(
        conn,
        "person_name_forms",
        {"name_form": name_form, "person_id": person_id, "sources": sources, "status": status},
        {"sources": "text[]", "status": "identifier_status"},
        returning=False,
        ignore_conflict=ignore_conflict,
    )


def insert_person_rh(
    conn: Connection,
    person_id: int,
    *,
    email: str | None = None,
    department_name: str | None = None,
    role_title: str | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> int:
    """Insère une fiche RH de la personne `person_id` et renvoie son `id`."""
    return insert_row(
        conn,
        "persons_rh",
        {
            "person_id": person_id,
            "email": email,
            "department_name": department_name,
            "role_title": role_title,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


def insert_rejected_authorship(
    conn: Connection, publication_id: int, *, person_id: int, ignore_conflict: bool = False
) -> None:
    """Rejette la paire publication ↔ personne, comme l'administration : un rejet par notice de la publication. Une publication sans notice en reçoit une. `ignore_conflict` ignore un rejet déjà présent."""
    conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "SELECT 'hal', 'rejet-' || :pub, 'X', :pub "
            "WHERE NOT EXISTS (SELECT 1 FROM source_publications WHERE publication_id = :pub)"
        ),
        {"pub": publication_id},
    )
    conflict = " ON CONFLICT DO NOTHING" if ignore_conflict else ""
    conn.execute(
        text(
            "INSERT INTO rejected_authorships (source_publication_id, person_id) "
            f"SELECT id, :pid FROM source_publications WHERE publication_id = :pub{conflict}"
        ),
        {"pub": publication_id, "pid": person_id},
    )
