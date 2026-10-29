"""Semis des contributions et des informations du contributeur, sur la connexion SQLAlchemy ou un curseur psycopg.

Le nom normalisé et les identifiants d'une contribution source sont dans la table dédupliquée `contributor_information`. `source_contributions` a seulement la clé étrangère `contributor_information_id`, que donnent `upsert_contributor_information` (connexion SQLAlchemy) et `upsert_contributor_information_on_cursor` (curseur psycopg).
"""

import json

from sqlalchemy import Connection, text

from tests.integration.helpers.rows import PERIMETER_EVIDENCE_CAST, insert_row, perimeter_evidence

# Paramètres au format psycopg (`%(nom)s`), que SQLAlchemy accepte via `exec_driver_sql`.
_INSERT_SQL = (
    "INSERT INTO contributor_information"
    " (last_name_normalized, first_name_normalized, identifiers)"
    " VALUES (%(last)s, %(first)s, CAST(%(ids)s AS jsonb)) ON CONFLICT DO NOTHING"
)
_SELECT_SQL = (
    "SELECT id FROM contributor_information"
    " WHERE last_name_normalized = %(last)s"
    "   AND first_name_normalized IS NOT DISTINCT FROM %(first)s"
    "   AND identifiers IS NOT DISTINCT FROM CAST(%(ids)s AS jsonb)"
)


def _params(last: str, first: str | None, identifiers: dict | None) -> dict:
    ids_json = json.dumps(identifiers) if identifiers is not None else None
    return {"last": last, "first": first or None, "ids": ids_json}


def _form_params(author_name_normalized: str | None, identifiers: dict | None) -> dict:
    """Forme « prénom nom » découpée au dernier espace : nom de famille à droite, prénom à gauche. La colonne calculée `author_name_normalized` redonne ainsi la forme reçue. `None` donne un nom vide."""
    first, _, last = (author_name_normalized or "").rpartition(" ")
    return _params(last, first, identifiers)


def _upsert(conn, params: dict) -> int:
    conn.exec_driver_sql(_INSERT_SQL, params)
    return conn.exec_driver_sql(_SELECT_SQL, params).scalar_one()


def upsert_contributor_information(conn, author_name_normalized=None, identifiers=None) -> int:
    """Upsert les informations du contributeur de forme normalisée `author_name_normalized` (« prénom nom ») et d'identifiants `identifiers` (dict ou `None`), sur une connexion SQLAlchemy, et renvoie son `id`."""
    return _upsert(conn, _form_params(author_name_normalized, identifiers))


def upsert_split_contributor_information(
    conn, last: str, first: str | None, identifiers=None
) -> int:
    """`upsert_contributor_information` d'après un nom et un prénom normalisés explicites."""
    return _upsert(conn, _params(last, first, identifiers))


def upsert_contributor_information_on_cursor(
    cur, author_name_normalized=None, identifiers=None
) -> int:
    """`upsert_contributor_information` sur un curseur psycopg à lignes en dictionnaire."""
    params = _form_params(author_name_normalized, identifiers)
    cur.execute(_INSERT_SQL, params)
    cur.execute(_SELECT_SQL, params)
    return cur.fetchone()["id"]


def insert_contribution(
    conn: Connection,
    publication_id: int,
    *,
    person_id: int,
    author_position: int | None = None,
    in_perimeter: bool | None = None,
    roles: list[str] | None = None,
) -> int:
    """Insère une contribution sans contribution source, rattachée à la personne `person_id` en mode `manual`, et renvoie son `id`. Une colonne laissée à `None` prend la valeur par défaut du schéma. `in_perimeter` pose l'indice `address`."""
    return insert_row(
        conn,
        "contributions",
        {
            "publication_id": publication_id,
            "person_id": person_id,
            "resolution_mode": "manual",
            "reference_position": author_position,
            "perimeter_evidence": perimeter_evidence(in_perimeter),
            "roles": roles,
        },
        {"perimeter_evidence": PERIMETER_EVIDENCE_CAST, "resolution_mode": "resolution_mode"},
    )


def contribution_id_of(conn: Connection, publication_id: int, person_id: int) -> int:
    """L'`id` de la contribution de la personne `person_id` dans la publication `publication_id`."""
    return conn.execute(
        text(
            "SELECT id FROM contributions"
            " WHERE publication_id = :publication AND person_id = :person"
        ),
        {"publication": publication_id, "person": person_id},
    ).scalar_one()


def insert_confirmed_source_contribution(
    conn: Connection, source_contribution_id: int, *, person_id: int
) -> None:
    """Épingle la contribution source `source_contribution_id` à la personne `person_id`."""
    insert_row(
        conn,
        "confirmed_source_contributions",
        {"source_contribution_id": source_contribution_id, "person_id": person_id},
        returning=False,
    )
