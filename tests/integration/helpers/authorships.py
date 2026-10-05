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
    """Upsert l'identité de forme normalisée `author_name_normalized` (« prénom nom ») et d'identifiants `person_identifiers` dans `author_identifying_keys`, et renvoie son `id`.

    La forme est découpée au dernier espace : nom de famille à droite, prénom à gauche. La colonne calculée `author_name_normalized` redonne ainsi la forme reçue. `None` donne un nom vide. `person_identifiers` est un dict (sérialisé en jsonb) ou `None`.
    """
    first, _, last = (author_name_normalized or "").rpartition(" ")
    ids_json = json.dumps(person_identifiers) if person_identifiers is not None else None
    params = {"last": last, "first": first or None, "ids": ids_json}
    conn.execute(
        text(
            "INSERT INTO author_identifying_keys"
            " (last_name_normalized, first_name_normalized, person_identifiers)"
            " VALUES (:last, :first, CAST(:ids AS jsonb)) ON CONFLICT DO NOTHING"
        ),
        params,
    )
    return conn.execute(
        text(
            "SELECT id FROM author_identifying_keys "
            "WHERE last_name_normalized = :last "
            "  AND first_name_normalized IS NOT DISTINCT FROM :first "
            "  AND person_identifiers IS NOT DISTINCT FROM CAST(:ids AS jsonb)"
        ),
        params,
    ).scalar_one()
