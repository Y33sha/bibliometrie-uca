"""Insertion d'une ligne sur la connexion SQLAlchemy, pour les fonctions de semis."""

from sqlalchemy import Connection, text

from domain.structures.perimeter_evidence import PerimeterEvidence

# Type SQL de la colonne `perimeter_evidence`, pour `casts`.
PERIMETER_EVIDENCE_CAST = "perimeter_evidence[]"


def perimeter_evidence(in_perimeter: bool | None) -> list[str] | None:
    """Renvoie les indices d'une ligne semée : l'adresse quand `in_perimeter` est vrai, sinon la valeur par défaut du schéma (aucun indice)."""
    return [PerimeterEvidence.ADDRESS.value] if in_perimeter else None


def insert_row(
    conn: Connection,
    table: str,
    values: dict[str, object],
    casts: dict[str, str] | None = None,
    *,
    nullable: tuple[str, ...] = (),
    returning: bool = True,
    ignore_conflict: bool = False,
) -> int | None:
    """Insère `values` dans `table` et renvoie l'`id`, ou `None` sans `returning` (table sans colonne `id`).

    Une colonne à `None` est omise et garde la valeur par défaut du schéma, sauf une colonne de `nullable`, écrite NULL. `casts` donne le type SQL des colonnes à convertir, par exemple une énumération. `ignore_conflict` ignore une ligne déjà présente.
    """
    casts = casts or {}
    values = {
        column: value for column, value in values.items() if value is not None or column in nullable
    }
    placeholders = [
        f"CAST(:{column} AS {casts[column]})" if column in casts else f":{column}"
        for column in values
    ]
    sql = f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(placeholders)})"
    if ignore_conflict:
        sql += " ON CONFLICT DO NOTHING"
    if not returning:
        conn.execute(text(sql), values)
        return None
    return conn.execute(text(sql + " RETURNING id"), values).scalar_one()
