"""Insertion d'une ligne sur la connexion SQLAlchemy, pour les fonctions de semis."""

from sqlalchemy import Connection, text


def insert_row(
    conn: Connection,
    table: str,
    values: dict[str, object],
    casts: dict[str, str] | None = None,
    *,
    nullable: tuple[str, ...] = (),
) -> int:
    """Insère `values` dans `table` et renvoie l'`id`.

    Une colonne à `None` est omise et garde la valeur par défaut du schéma, sauf une colonne de `nullable`, écrite NULL. `casts` donne le type SQL des colonnes à convertir, par exemple une énumération.
    """
    casts = casts or {}
    values = {
        column: value for column, value in values.items() if value is not None or column in nullable
    }
    placeholders = [
        f"CAST(:{column} AS {casts[column]})" if column in casts else f":{column}"
        for column in values
    ]
    return conn.execute(
        text(
            f"INSERT INTO {table} ({', '.join(values)}) "
            f"VALUES ({', '.join(placeholders)}) RETURNING id"
        ),
        values,
    ).scalar_one()
