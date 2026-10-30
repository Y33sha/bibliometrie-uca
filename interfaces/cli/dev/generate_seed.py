# STATUS: recurring (dev)
"""Génère le seed commun et le seed d'établissement à partir des données de référence de la base courante.

Le seed commun (`infrastructure/db/seed.sql`) contient les référentiels partagés par tous les établissements, et la valeur initiale des clés de configuration communes (`INITIAL_CONFIG_VALUES`). Le chargement d'un seed garde la configuration en base. Le seed d'établissement (`infrastructure/db/seed_uca.sql` pour UCA) contient les structures, leurs tutelles, les périmètres, les formes de noms, les clés de configuration propres à l'établissement. Les deux seeds se chargent indépendamment l'un de l'autre.

Usage :
    uv run python -m interfaces.cli.dev.generate_seed
    uv run python -m interfaces.cli.dev.generate_seed --common-output CHEMIN --institution-output CHEMIN

Chaque fichier produit est un SQL pur qui aligne les tables sur le seed (`render_seed`) et recale les séquences. Il suppose le schéma appliqué par les migrations.
"""

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from sqlalchemy import Column, Connection, Table, text
from sqlalchemy.sql.base import ReadOnlyColumnCollection

from domain.config import INITIAL_CONFIG_VALUES, INSTITUTION_CONFIG_KEYS
from domain.types import JsonValue
from infrastructure import PROJECT_ROOT
from infrastructure.db import tables
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb

_DB_DIR = PROJECT_ROOT / "infrastructure" / "db"

# Colonnes absentes de l'export : l'horodatage d'insertion reprend sa valeur par défaut au chargement.
EXCLUDED_COLUMNS = frozenset({"created_at"})


type SeedTable = Table[ReadOnlyColumnCollection[str, Column[object]]]
"""Table du schéma, quelles que soient ses colonnes."""


class _TableExportee(TypedDict):
    table: SeedTable


class TableSpec(_TableExportee, total=False):
    """Table de référence à exporter.

    Toutes les colonnes de la table sont exportées, sauf celles de `EXCLUDED_COLUMNS`, et les lignes sont triées par clé.
    """

    where: str
    """Restreint les lignes exportées et supprimées au chargement."""
    key: tuple[str, ...]
    """Identifie une ligne d'une base à l'autre, à défaut de la clé primaire, alors absente de l'export."""
    keep_existing: bool
    """Garde les lignes de la base au chargement : le seed ajoute seulement les lignes absentes."""
    rows: Callable[[Connection], list[tuple[JsonValue, ...]]]
    """Fournit les lignes à la place de la base."""


@dataclass(frozen=True)
class SeedSpec:
    """Seed à produire."""

    description: str
    """Description en tête de fichier."""
    tables: tuple[TableSpec, ...]
    """Tables dans l'ordre d'insertion, celui des clés étrangères."""
    default_path: Path


@dataclass(frozen=True)
class SeedSection:
    """Lignes d'une table à écrire dans un seed."""

    table: SeedTable
    rows: list[tuple[JsonValue, ...]]
    """Valeurs dans l'ordre de `exported_columns`."""
    where: str | None = None
    """Restreint les lignes supprimées au chargement."""
    key: tuple[str, ...] | None = None
    """Identifie une ligne, à défaut de la clé primaire."""
    keep_existing: bool = False
    """Garde les lignes de la base au chargement."""


def initial_config_rows(conn: Connection) -> list[tuple[JsonValue, ...]]:
    """Renvoie les clés communes de la configuration avec leur valeur initiale (`INITIAL_CONFIG_VALUES`) et leur description en base."""
    descriptions = dict(
        conn.execute(
            text("SELECT key, description FROM config WHERE key = ANY(:keys)"),
            {"keys": list(INITIAL_CONFIG_VALUES)},
        ).all()
    )
    return [
        (key, value, descriptions.get(key)) for key, value in sorted(INITIAL_CONFIG_VALUES.items())
    ]


_INSTITUTION_KEYS_SQL = ", ".join(f"'{key}'" for key in sorted(INSTITUTION_CONFIG_KEYS))

COMMON_SEED = SeedSpec(
    description="Seed commun : référentiels partagés par tous les établissements.",
    tables=(
        {"table": tables.config, "keep_existing": True, "rows": initial_config_rows},
        {"table": tables.countries},
        {"table": tables.languages},
        {"table": tables.language_forms},
        # Des migrations insèrent des formes : leur identifiant diffère d'une base à l'autre.
        {
            "table": tables.place_name_forms,
            "where": "kind <> 'institution'",
            "key": ("form_normalized",),
        },
    ),
    default_path=_DB_DIR / "seed.sql",
)

INSTITUTION_SEED = SeedSpec(
    description=(
        "Seed d'établissement : structures, tutelles, périmètres, formes de noms, "
        "clés de configuration propres à l'établissement."
    ),
    tables=(
        {"table": tables.structures},
        {"table": tables.structure_parents},
        {"table": tables.perimeters},
        {"table": tables.structure_name_forms},
        {
            "table": tables.config,
            "where": f"key IN ({_INSTITUTION_KEYS_SQL})",
            "keep_existing": True,
        },
    ),
    default_path=_DB_DIR / "seed_uca.sql",
)


def exported_columns(table: SeedTable, key: Sequence[str] | None = None) -> list[str]:
    """Renvoie les colonnes exportées de `table`, dans l'ordre de sa définition. Avec une clé `key`, la clé primaire est omise."""
    omitted = EXCLUDED_COLUMNS | (
        {c.name for c in table.primary_key.columns} - set(key) if key else set()
    )
    return [c.name for c in table.columns if c.name not in omitted]


def row_key(table: SeedTable, key: Sequence[str] | None = None) -> list[str]:
    """Renvoie les colonnes identifiant une ligne de `table` : `key`, à défaut la clé primaire."""
    return list(key) if key else [c.name for c in table.primary_key.columns]


def escape_sql(value: JsonValue, is_jsonb: bool = False) -> str:
    """Échappe une valeur pour une insertion SQL ; une valeur de colonne JSONB devient du JSON valide."""
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
    """Renvoie le chemin relatif à la racine du dépôt quand le fichier s'y trouve, absolu sinon. Les séparateurs sont des barres obliques, quel que soit le système."""
    resolved = path.resolve()
    if resolved.is_relative_to(PROJECT_ROOT):
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    return resolved.as_posix()


def _upsert_clause(columns: Sequence[str], key: Sequence[str]) -> str:
    """Renvoie la clause `ON CONFLICT` qui met à jour une ligne existante de même clé primaire avec les valeurs du seed."""
    updated = [c for c in columns if c not in key]
    if not updated:
        return f" ON CONFLICT ({', '.join(key)}) DO NOTHING"
    assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in updated)
    return f" ON CONFLICT ({', '.join(key)}) DO UPDATE SET {assignments}"


def render_seed(description: str, output_path: Path, sections: Sequence[SeedSection]) -> str:
    """Renvoie le texte SQL d'un seed : une transaction qui aligne chaque table sur le seed, et recale les séquences.

    Une table perd les lignes absentes du seed. Elle reçoit les autres, mises à jour sur place quand leur clé (`row_key`) existe : les lignes qui les référencent restent intactes. Une section `keep_existing` garde toutes les lignes de la base et ajoute seulement les lignes absentes.
    """
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
        columns = exported_columns(section.table, section.key)
        if not section.rows:
            lines += [f"-- {table} : aucune donnée", ""]
            continue

        col_list = ", ".join(columns)
        key = row_key(section.table, section.key)
        jsonb_cols = {c.name for c in section.table.columns if isinstance(c.type, type(Jsonb))}
        lines.append(f"-- {table} ({len(section.rows)} lignes)")
        if section.keep_existing:
            upsert = _upsert_clause(key, key)
        else:
            key_positions = [columns.index(c) for c in key]
            kept = ", ".join(
                "(" + ", ".join(escape_sql(row[i]) for i in key_positions) + ")"
                for row in section.rows
            )
            conditions = [f"({section.where})"] if section.where else []
            conditions.append(f"({', '.join(key)}) NOT IN ({kept})")
            upsert = _upsert_clause(columns, key)
            lines.append(f"DELETE FROM {table} WHERE {' AND '.join(conditions)};")
        for row in section.rows:
            values = ", ".join(
                escape_sql(value, is_jsonb=(column in jsonb_cols))
                for column, value in zip(columns, row, strict=True)
            )
            lines.append(f"INSERT INTO {table} ({col_list}) VALUES ({values}){upsert};")

        # Recalage des séquences des tables à id serial.
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
    """Lit les lignes de chaque table du seed : celles de `rows` s'il est donné, sinon celles de la base courante, triées par clé (`row_key`)."""
    sections = []
    for spec in seed.tables:
        table = spec["table"]
        where = spec.get("where")
        key = spec.get("key")
        reader = spec.get("rows")
        if reader is not None:
            rows = reader(conn)
        else:
            filtre = f" WHERE {where}" if where else ""
            col_list = ", ".join(exported_columns(table, key))
            order = ", ".join(row_key(table, key))
            result = conn.execute(
                text(f"SELECT {col_list} FROM {table.name}{filtre} ORDER BY {order}")
            )
            rows = [tuple(row) for row in result]
        keep_existing = spec.get("keep_existing", False)
        sections.append(SeedSection(table, rows, where, key, keep_existing))
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
