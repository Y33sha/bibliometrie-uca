"""
Génère db/seed.sql à partir des données de référence de la base courante.

Tables exportées :
  - config              (paramètres applicatifs)
  - countries           (référentiel pays)
  - country_name_forms  (formes de noms de pays)
  - structures          (structures UCA, labos, partenaires)
  - structure_relations  (relations entre structures)
  - perimeters          (périmètres UCA, UCA élargi)
  - structure_name_forms (formes de noms pour le matching d'adresses)

Usage :
    python scripts/generate_seed.py
    python scripts/generate_seed.py --output db/seed.sql

Le fichier produit est un SQL pur (INSERT) avec gestion des séquences.
Il suppose que le schéma (tables, enums, séquences) est déjà appliqué
via db/schema.sql + migrations.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

# Tables à exporter, dans l'ordre d'insertion (respect des FK)
TABLES = [
    {
        "table": "config",
        "columns": ["key", "value", "description"],
        "order": "key",
        "jsonb_columns": ["value"],
        # Clés contenant des credentials — remplacées par des placeholders
        "redact": {
            "wos_api_key": "VOTRE_CLE_WOS",
            "scanr_password": "VOTRE_MOT_DE_PASSE_SCANR",
            "scanr_username": "VOTRE_IDENTIFIANT_SCANR",
            "openalex_email": "votre@email.fr",
        },
    },
    {
        "table": "countries",
        "columns": ["code", "name"],
        "order": "code",
    },
    {
        "table": "country_name_forms",
        "columns": ["id", "iso_code", "form_normalized"],
        "order": "id",
    },
    {
        "table": "structures",
        "columns": ["id", "code", "name", "acronym", "structure_type", "ror_id", "rnsr_id", "hal_collection"],
        "order": "id",
    },
    {
        "table": "structure_relations",
        "columns": ["id", "parent_id", "child_id", "relation_type"],
        "order": "id",
    },
    {
        "table": "perimeters",
        "columns": ["id", "code", "name", "description", "structure_ids"],
        "order": "id",
    },
    {
        "table": "structure_name_forms",
        "columns": ["id", "structure_id", "form_text", "requires_context_of", "is_word_boundary", "is_excluding"],
        "order": "id",
    },
]


def escape_sql(value, is_jsonb=False) -> str:
    """Échappe une valeur pour insertion SQL.

    Si is_jsonb=True, la valeur est sérialisée en JSON valide
    (nécessaire pour les colonnes JSONB de PostgreSQL).
    """
    import json
    if value is None:
        return "NULL"
    if is_jsonb:
        s = json.dumps(value, ensure_ascii=False).replace("'", "''")
        return f"'{s}'"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        # Arrays PostgreSQL : '{1,2,3}' ou '{"a","b"}'
        elements = ", ".join(str(v).replace("'", "''") for v in value)
        return "'{" + elements + "}'"
    if isinstance(value, dict):
        s = json.dumps(value, ensure_ascii=False).replace("'", "''")
        return f"'{s}'"
    s = str(value).replace("'", "''")
    return f"'{s}'"


def generate_seed(cur, output_path: str):
    lines = []
    lines.append("-- Seed généré automatiquement par scripts/generate_seed.py")
    lines.append("-- Ne pas modifier à la main — relancer le script pour régénérer.")
    lines.append("--")
    lines.append("-- Prérequis : schéma appliqué (db/schema.sql + migrations)")
    lines.append("-- Usage : psql -d bibliometrie -f db/seed.sql")
    lines.append("")
    lines.append("BEGIN;")
    lines.append("")

    for spec in TABLES:
        table = spec["table"]
        columns = spec["columns"]
        order = spec["order"]

        col_list = ", ".join(columns)
        cur.execute(f"SELECT {col_list} FROM {table} ORDER BY {order}")
        rows = cur.fetchall()

        if not rows:
            lines.append(f"-- {table} : aucune donnée")
            lines.append("")
            continue

        lines.append(f"-- {table} ({len(rows)} lignes)")
        lines.append(f"DELETE FROM {table};")

        redact = spec.get("redact", {})
        jsonb_cols = set(spec.get("jsonb_columns", []))
        key_idx = columns.index("key") if "key" in columns else None
        value_idx = columns.index("value") if "value" in columns else None

        for row in rows:
            row_values = list(row)
            # Remplacer les credentials par des placeholders
            if redact and key_idx is not None and value_idx is not None:
                row_key = row_values[key_idx]
                if row_key in redact:
                    row_values[value_idx] = redact[row_key]
            values = ", ".join(
                escape_sql(row_values[i], is_jsonb=(columns[i] in jsonb_cols))
                for i in range(len(columns))
            )
            lines.append(f"INSERT INTO {table} ({col_list}) VALUES ({values});")

        # Recaler les séquences pour les tables avec id serial
        if "id" in columns:
            lines.append(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT COALESCE(MAX(id), 0) FROM {table}));")

        lines.append("")

    lines.append("COMMIT;")
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Seed généré : {output_path} ({len(rows)} lignes pour la dernière table)")
    for spec in TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {spec['table']}")
        count = cur.fetchone()[0]
        print(f"  {spec['table']}: {count} lignes")


def main():
    parser = argparse.ArgumentParser(description="Génère db/seed.sql depuis la base courante")
    parser.add_argument("--output", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "seed.sql"))
    args = parser.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        generate_seed(cur, args.output)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
