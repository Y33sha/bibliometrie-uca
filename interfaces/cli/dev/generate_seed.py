# STATUS: recurring (dev)
"""Génère le seed commun et le seed d'établissement à partir des données de référence de la base courante.

Le seed commun (`infrastructure/db/seed.sql`) contient les référentiels partagés par tous les établissements. Le seed d'établissement (`infrastructure/db/seed_uca.sql` pour UCA) contient les structures, leurs tutelles, les périmètres, les formes de noms et les clés de configuration qui désignent les périmètres. Les deux seeds se chargent indépendamment l'un de l'autre.

Usage :
    python -m interfaces.cli.dev.generate_seed
    python -m interfaces.cli.dev.generate_seed --common-output CHEMIN --institution-output CHEMIN

Chaque fichier produit est un SQL pur (INSERT) avec recalage des séquences. Il suppose le schéma appliqué par les migrations.
"""

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from sqlalchemy import Connection, Table, text

from domain.config import INSTITUTION_CONFIG_KEYS
from domain.types import JsonValue
from infrastructure import PROJECT_ROOT
from infrastructure.db import tables
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb

_DB_DIR = PROJECT_ROOT / "infrastructure" / "db"

# Colonnes absentes de l'export : l'horodatage d'insertion reprend sa valeur par défaut au chargement.
EXCLUDED_COLUMNS = frozenset({"created_at"})


class _TableExportee(TypedDict):
    table: Table


class TableSpec(_TableExportee, total=False):
    """Table de référence à exporter.

    Toutes les colonnes de la table sont exportées, sauf celles de `EXCLUDED_COLUMNS`, et les lignes sont triées par clé primaire. `where` restreint les lignes exportées et supprimées au chargement.
    """

    where: str


@dataclass(frozen=True)
class SeedSpec:
    """Seed à produire : description en tête de fichier, tables dans l'ordre d'insertion (respect des FK), fichier par défaut."""

    description: str
    tables: tuple[TableSpec, ...]
    default_path: Path


@dataclass(frozen=True)
class SeedSection:
    """Lignes d'une table à écrire dans un seed, valeurs dans l'ordre de `exported_columns`. `where` restreint les lignes supprimées au chargement."""

    table: Table
    rows: list[tuple[JsonValue, ...]]
    where: str | None = None


_INSTITUTION_KEYS_SQL = ", ".join(f"'{key}'" for key in sorted(INSTITUTION_CONFIG_KEYS))

COMMON_SEED = SeedSpec(
    description="Seed commun : référentiels partagés par tous les établissements.",
    tables=(
        {"table": tables.config, "where": f"key NOT IN ({_INSTITUTION_KEYS_SQL})"},
        {"table": tables.countries},
        {"table": tables.place_name_forms, "where": "kind <> 'institution'"},
    ),
    default_path=_DB_DIR / "seed.sql",
)

INSTITUTION_SEED = SeedSpec(
    description=(
        "Seed d'établissement : structures, tutelles, périmètres, formes de noms "
        "et clés de configuration des périmètres."
    ),
    tables=(
        {"table": tables.structures},
        {"table": tables.structure_tutelles},
        {"table": tables.perimeters},
        {"table": tables.structure_name_forms},
        {"table": tables.config, "where": f"key IN ({_INSTITUTION_KEYS_SQL})"},
    ),
    default_path=_DB_DIR / "seed_uca.sql",
)


def exported_columns(table: Table) -> list[str]:
    """Colonnes exportées de `table`, dans l'ordre de sa définition."""
    return [c.name for c in table.columns if c.name not in EXCLUDED_COLUMNS]


def escape_sql(value: JsonValue, is_jsonb: bool = False) -> str:
    """Échappe une valeur pour insertion SQL.

    Si is_jsonb=True, la valeur est sérialisée en JSON valide (nécessaire pour les colonnes JSONB de PostgreSQL).
    """
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
        # Array PostgreSQL en forme non quotée '{1,2,3}' ; les seules colonnes array du seed sont des integer[].
        elements = ", ".join(str(v).replace("'", "''") for v in value)
        return "'{" + elements + "}'"
    if isinstance(value, dict):
        s = json.dumps(value, ensure_ascii=False).replace("'", "''")
        return f"'{s}'"
    s = str(value).replace("'", "''")
    return f"'{s}'"


def _display_path(path: Path) -> str:
    """Chemin relatif à la racine du dépôt quand le fichier s'y trouve, absolu sinon."""
    resolved = path.resolve()
    if resolved.is_relative_to(PROJECT_ROOT):
        return str(resolved.relative_to(PROJECT_ROOT))
    return str(resolved)


def render_seed(description: str, output_path: Path, sections: Sequence[SeedSection]) -> str:
    """Texte SQL d'un seed : une transaction qui vide puis remplit chaque table, et recale les séquences."""
    lines = [
        "-- Seed généré automatiquement par interfaces/cli/dev/generate_seed.py",
        "-- Ne pas modifier à la main — relancer le script pour régénérer.",
        "--",
        f"-- {description}",
        "-- Prérequis : schéma appliqué par les migrations (alembic upgrade head)",
        f"-- Usage : psql -d bibliometrie -f {_display_path(output_path)}",
        "",
        "BEGIN;",
        "",
    ]
    for section in sections:
        table = section.table.name
        columns = exported_columns(section.table)
        if not section.rows:
            lines += [f"-- {table} : aucune donnée", ""]
            continue

        col_list = ", ".join(columns)
        filtre = f" WHERE {section.where}" if section.where else ""
        jsonb_cols = {c.name for c in section.table.columns if isinstance(c.type, type(Jsonb))}
        lines.append(f"-- {table} ({len(section.rows)} lignes)")
        lines.append(f"DELETE FROM {table}{filtre};")
        for row in section.rows:
            values = ", ".join(
                escape_sql(value, is_jsonb=(column in jsonb_cols))
                for column, value in zip(columns, row, strict=True)
            )
            lines.append(f"INSERT INTO {table} ({col_list}) VALUES ({values});")

        # Recaler les séquences pour les tables avec id serial
        if "id" in columns:
            lines.append(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 0) FROM {table}));"
            )
        lines.append("")

    lines += ["COMMIT;", ""]
    return "\n".join(lines)


def write_seed(description: str, output_path: Path, sections: Sequence[SeedSection]) -> None:
    """Écrit le seed dans `output_path` et affiche le nombre de lignes de chaque table."""
    output_path.write_text(render_seed(description, output_path, sections), encoding="utf-8")
    print(f"Seed généré : {output_path}")
    for section in sections:
        print(f"  {section.table.name}: {len(section.rows)} lignes")


def read_sections(conn: Connection, seed: SeedSpec) -> list[SeedSection]:
    """Lignes de la base courante pour chaque table du seed, triées par clé primaire."""
    sections = []
    for spec in seed.tables:
        table = spec["table"]
        where = spec.get("where")
        filtre = f" WHERE {where}" if where else ""
        col_list = ", ".join(exported_columns(table))
        order = ", ".join(c.name for c in table.primary_key.columns)
        rows = conn.execute(
            text(f"SELECT {col_list} FROM {table.name}{filtre} ORDER BY {order}")
        ).all()
        sections.append(SeedSection(table, [tuple(row) for row in rows], where))
    return sections


def generate_seed(conn: Connection, seed: SeedSpec, output_path: Path) -> None:
    write_seed(seed.description, output_path, read_sections(conn, seed))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère le seed commun et le seed d'établissement depuis la base courante"
    )
    parser.add_argument("--common-output", type=Path, default=COMMON_SEED.default_path)
    parser.add_argument("--institution-output", type=Path, default=INSTITUTION_SEED.default_path)
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        generate_seed(conn, COMMON_SEED, args.common_output)
        generate_seed(conn, INSTITUTION_SEED, args.institution_output)


if __name__ == "__main__":
    main()
