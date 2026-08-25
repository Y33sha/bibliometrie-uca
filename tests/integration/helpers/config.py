"""Helper de test : insérer une ligne dans la table `config`.

Plusieurs suites d'application sèment des paramètres de configuration ; elles passent par `insert_config` plutôt que de dupliquer l'INSERT dans chaque fichier.
"""

import json

from sqlalchemy import text


def insert_config(conn, key, value, description="desc") -> None:
    """Insère `(key, value, description)` dans `config`, `value` sérialisé en jsonb."""
    conn.execute(
        text(
            "INSERT INTO config (key, value, description) "
            "VALUES (:key, CAST(:value AS jsonb), :description)"
        ),
        {"key": key, "value": json.dumps(value), "description": description},
    )
