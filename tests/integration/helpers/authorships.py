"""Helper de test : matérialiser l'identité d'auteur d'une `source_authorships`.

Le nom normalisé et les identifiants d'une signature vivent dans la table
d'identités dédupliquée `author_identifying_keys` ; `source_authorships` ne
porte qu'une FK `identity_id`. Les tests qui sèment des signatures passent par
`upsert_identity` pour obtenir l'`identity_id` correspondant, plutôt que de
dupliquer l'upsert de l'identité dans chaque fichier.
"""

import json

from sqlalchemy import text


def upsert_identity(conn, author_name_normalized=None, person_identifiers=None) -> int:
    """Upsert l'identité `(author_name_normalized, person_identifiers)` dans
    `author_identifying_keys` et renvoie son `id`. `person_identifiers` est un
    dict (sérialisé en jsonb) ou `None`. Le rapprochement est NULL-safe
    (`IS NOT DISTINCT FROM`), suffisant au volume des tests."""
    ids_json = json.dumps(person_identifiers) if person_identifiers is not None else None
    conn.execute(
        text(
            "INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers) "
            "VALUES (:anf, CAST(:ids AS jsonb)) ON CONFLICT DO NOTHING"
        ),
        {"anf": author_name_normalized, "ids": ids_json},
    )
    return conn.execute(
        text(
            "SELECT id FROM author_identifying_keys "
            "WHERE author_name_normalized IS NOT DISTINCT FROM :anf "
            "  AND person_identifiers IS NOT DISTINCT FROM CAST(:ids AS jsonb)"
        ),
        {"anf": author_name_normalized, "ids": ids_json},
    ).scalar_one()
