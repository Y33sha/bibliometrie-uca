"""Semis des authorships et des identités d'auteur, sur la connexion SQLAlchemy ou un curseur psycopg.

Le nom normalisé et les identifiants d'une signature vivent dans la table
d'identités dédupliquée `author_identifying_keys` ; `source_authorships` ne
porte qu'une FK `identity_id`. Les tests qui sèment des signatures passent par
`upsert_identity` (connexion SQLAlchemy) ou `upsert_identity_on_cursor` (curseur
psycopg) pour obtenir l'`identity_id` correspondant.
"""

import json

from sqlalchemy import Connection

from tests.integration.helpers.rows import PERIMETER_EVIDENCE_CAST, insert_row, perimeter_evidence

# Paramètres au format psycopg (`%(nom)s`), que SQLAlchemy accepte via `exec_driver_sql`.
_INSERT_SQL = (
    "INSERT INTO author_identifying_keys"
    " (last_name_normalized, first_name_normalized, person_identifiers)"
    " VALUES (%(last)s, %(first)s, CAST(%(ids)s AS jsonb)) ON CONFLICT DO NOTHING"
)
_SELECT_SQL = (
    "SELECT id FROM author_identifying_keys"
    " WHERE last_name_normalized = %(last)s"
    "   AND first_name_normalized IS NOT DISTINCT FROM %(first)s"
    "   AND person_identifiers IS NOT DISTINCT FROM CAST(%(ids)s AS jsonb)"
)


def _params(last: str, first: str | None, person_identifiers: dict | None) -> dict:
    ids_json = json.dumps(person_identifiers) if person_identifiers is not None else None
    return {"last": last, "first": first or None, "ids": ids_json}


def _form_params(author_name_normalized: str | None, person_identifiers: dict | None) -> dict:
    """Forme « prénom nom » découpée au dernier espace : nom de famille à droite, prénom à gauche. La colonne calculée `author_name_normalized` redonne ainsi la forme reçue. `None` donne un nom vide."""
    first, _, last = (author_name_normalized or "").rpartition(" ")
    return _params(last, first, person_identifiers)


def _upsert(conn, params: dict) -> int:
    conn.exec_driver_sql(_INSERT_SQL, params)
    return conn.exec_driver_sql(_SELECT_SQL, params).scalar_one()


def upsert_identity(conn, author_name_normalized=None, person_identifiers=None) -> int:
    """Upsert l'identité de forme normalisée `author_name_normalized` (« prénom nom ») et d'identifiants `person_identifiers` (dict ou `None`), sur une connexion SQLAlchemy, et renvoie son `id`."""
    return _upsert(conn, _form_params(author_name_normalized, person_identifiers))


def upsert_split_identity(conn, last: str, first: str | None, person_identifiers=None) -> int:
    """`upsert_identity` d'après un nom et un prénom normalisés explicites."""
    return _upsert(conn, _params(last, first, person_identifiers))


def upsert_identity_on_cursor(cur, author_name_normalized=None, person_identifiers=None) -> int:
    """`upsert_identity` sur un curseur psycopg à lignes en dictionnaire."""
    params = _form_params(author_name_normalized, person_identifiers)
    cur.execute(_INSERT_SQL, params)
    cur.execute(_SELECT_SQL, params)
    return cur.fetchone()["id"]


def insert_authorship(
    conn: Connection,
    publication_id: int,
    *,
    person_id: int,
    author_position: int | None = None,
    in_perimeter: bool | None = None,
    roles: list[str] | None = None,
) -> int:
    """Insère une authorship et renvoie son `id`. Une colonne laissée à `None` prend la valeur par défaut du schéma. `in_perimeter` pose l'indice `address`."""
    return insert_row(
        conn,
        "authorships",
        {
            "publication_id": publication_id,
            "person_id": person_id,
            "author_position": author_position,
            "perimeter_evidence": perimeter_evidence(in_perimeter),
            "roles": roles,
        },
        {"perimeter_evidence": PERIMETER_EVIDENCE_CAST},
    )


def insert_confirmed_authorship(
    conn: Connection, source_authorship_id: int, *, person_id: int
) -> None:
    """Épingle la signature `source_authorship_id` à la personne `person_id`."""
    insert_row(
        conn,
        "confirmed_authorships",
        {"source_authorship_id": source_authorship_id, "person_id": person_id},
        returning=False,
    )
