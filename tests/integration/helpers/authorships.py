"""Helper de test : matérialiser l'identité d'auteur d'une `source_authorships`.

Le nom normalisé et les identifiants d'une signature vivent dans la table
d'identités dédupliquée `author_identifying_keys` ; `source_authorships` ne
porte qu'une FK `identity_id`. Les tests qui sèment des signatures passent par
`upsert_identity` (connexion SQLAlchemy) ou `upsert_identity_on_cursor` (curseur
psycopg) pour obtenir l'`identity_id` correspondant.
"""

import json

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


def _params(author_name_normalized: str | None, person_identifiers: dict | None) -> dict:
    """Forme « prénom nom » découpée au dernier espace : nom de famille à droite, prénom à gauche. La colonne calculée `author_name_normalized` redonne ainsi la forme reçue. `None` donne un nom vide."""
    first, _, last = (author_name_normalized or "").rpartition(" ")
    ids_json = json.dumps(person_identifiers) if person_identifiers is not None else None
    return {"last": last, "first": first or None, "ids": ids_json}


def upsert_identity(conn, author_name_normalized=None, person_identifiers=None) -> int:
    """Upsert l'identité de forme normalisée `author_name_normalized` (« prénom nom ») et d'identifiants `person_identifiers` (dict ou `None`), sur une connexion SQLAlchemy, et renvoie son `id`."""
    params = _params(author_name_normalized, person_identifiers)
    conn.exec_driver_sql(_INSERT_SQL, params)
    return conn.exec_driver_sql(_SELECT_SQL, params).scalar_one()


def upsert_identity_on_cursor(cur, author_name_normalized=None, person_identifiers=None) -> int:
    """`upsert_identity` sur un curseur psycopg à lignes en dictionnaire."""
    params = _params(author_name_normalized, person_identifiers)
    cur.execute(_INSERT_SQL, params)
    cur.execute(_SELECT_SQL, params)
    return cur.fetchone()["id"]
