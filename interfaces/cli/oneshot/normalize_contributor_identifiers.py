# STATUS: oneshot (2026-10-21)
"""Met les identifiants de `contributor_information` sous la forme que leur donne `compact_identifiers`.

`compact_identifiers` normalise chaque identifiant de personne par le value object de son type, écrit `hal_person_id` en chaîne et écarte une valeur mal formée. Le script applique cette forme aux lignes existantes :

- une ligne dont la clé (noms normalisés, identifiants) devient celle d'une autre ligne est fusionnée dans celle-ci : ses contributions sources passent à l'autre ligne, puis elle est supprimée ;
- les autres lignes reçoivent leurs identifiants normalisés ;
- dans les enregistrements sources dont une valeur d'identifiant change, les contributions sources recalculent leurs neutralisations pour cause de partage (`shared_identifier_neutralizations`), et les publications de ces enregistrements sources sont marquées à regrouper (`contributions_dirty`).

Usage :
    python -m interfaces.cli.oneshot.normalize_contributor_identifiers [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import cast

from sqlalchemy import Connection, Row, bindparam, text

from domain.persons.identifiers import (
    IdentifierNeutralization,
    compact_identifiers,
    shared_identifier_neutralizations,
)
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger

log = setup_logger("normalize_contributor_identifiers", os.path.dirname(__file__))


@dataclass(frozen=True)
class ContributorInformationRow:
    id: int
    last_name_normalized: str
    first_name_normalized: str | None
    identifiers: dict[str, JsonValue] | None


@dataclass
class Plan:
    """`updates` : `(id, identifiers normalisés)`. `merges` : `(id fusionné, id gardé)`. `changed_values` : lignes dont une valeur d'identifiant change, au-delà du passage de `hal_person_id` en chaîne."""

    updates: list[tuple[int, dict[str, JsonValue] | None]] = field(default_factory=list)
    merges: list[tuple[int, int]] = field(default_factory=list)
    changed_values: set[int] = field(default_factory=set)
    malformed: Counter[str] = field(default_factory=Counter)


def _key(
    row: ContributorInformationRow, identifiers: Mapping[str, JsonValue] | None
) -> tuple[str, str | None, str | None]:
    return (
        row.last_name_normalized,
        row.first_name_normalized,
        None if identifiers is None else json.dumps(identifiers, sort_keys=True),
    )


def plan(rows: Iterable[ContributorInformationRow]) -> Plan:
    """Calcule les mises à jour et les fusions. `compact_identifiers` est idempotent : la clé cible d'une ligne modifiée diffère de la clé courante de toute ligne modifiée."""
    rows = sorted(rows, key=lambda r: r.id)
    id_by_key = {_key(r, r.identifiers): r.id for r in rows}
    result = Plan()
    for row in rows:
        if row.identifiers is None:
            continue
        normalized = compact_identifiers(**cast("dict[str, str | int | None]", row.identifiers))
        if normalized.values == row.identifiers:
            continue
        result.malformed.update(id_type for id_type, _ in normalized.malformed)
        if normalized.values != {k: str(v) for k, v in row.identifiers.items()}:
            result.changed_values.add(row.id)
        del id_by_key[_key(row, row.identifiers)]
        target_key = _key(row, normalized.values)
        if (kept := id_by_key.get(target_key)) is not None:
            result.merges.append((row.id, kept))
        else:
            result.updates.append((row.id, normalized.values))
            id_by_key[target_key] = row.id
    return result


def fetch_rows(conn: Connection) -> list[ContributorInformationRow]:
    return [
        ContributorInformationRow(
            r.id, r.last_name_normalized, r.first_name_normalized, r.identifiers
        )
        for r in conn.execute(
            text(
                "SELECT id, last_name_normalized, first_name_normalized, identifiers FROM contributor_information"
            )
        )
    ]


def apply(conn: Connection, result: Plan) -> int:
    """Écrit le plan. Rend le nombre de contributions sources dont les neutralisations changent."""
    affected = list(
        conn.execute(
            text("""
                SELECT DISTINCT source_record_id FROM source_contributions
                WHERE contributor_information_id = ANY(:ids)
            """),
            {"ids": list(result.changed_values)},
        ).scalars()
    )
    if result.updates:
        conn.execute(
            text("""
                UPDATE contributor_information ci SET identifiers = t.identifiers
                FROM jsonb_to_recordset(:payload) AS t(id integer, identifiers jsonb)
                WHERE ci.id = t.id
            """).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": [{"id": i, "identifiers": v} for i, v in result.updates]},
        )
    if result.merges:
        conn.execute(
            text("""
                UPDATE source_contributions sc SET contributor_information_id = t.kept
                FROM jsonb_to_recordset(:payload) AS t(merged integer, kept integer)
                WHERE sc.contributor_information_id = t.merged
            """).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": [{"merged": m, "kept": k} for m, k in result.merges]},
        )
        conn.execute(
            text("DELETE FROM contributor_information WHERE id = ANY(:ids)"),
            {"ids": [m for m, _ in result.merges]},
        )
    changed = _recompute_shared_neutralizations(conn, affected)
    conn.execute(
        text("""
            UPDATE publications p SET contributions_dirty = true
            FROM source_records sr
            WHERE sr.id = ANY(:ids) AND p.id = sr.publication_id AND NOT p.contributions_dirty
        """),
        {"ids": affected},
    )
    return changed


def _recompute_shared_neutralizations(conn: Connection, source_record_ids: list[int]) -> int:
    """Recalcule les neutralisations pour cause de partage des contributions sources de ces enregistrements sources. Une neutralisation `misplaced` reste, sauf sur un identifiant neutralisé pour cause de partage."""
    rows = conn.execute(
        text("""
            SELECT sc.id, sc.source_record_id, ci.identifiers, sc.neutralized_identifiers
            FROM source_contributions sc
            JOIN contributor_information ci ON ci.id = sc.contributor_information_id
            WHERE sc.source_record_id = ANY(:ids)
            ORDER BY sc.source_record_id, sc.id
        """),
        {"ids": source_record_ids},
    ).all()
    by_record: dict[int, list[Row[tuple[object, ...]]]] = {}
    for r in rows:
        by_record.setdefault(r.source_record_id, []).append(r)
    changes: list[dict[str, JsonValue]] = []
    for contributions in by_record.values():
        shared = shared_identifier_neutralizations([c.identifiers for c in contributions])
        for c, shared_map in zip(contributions, shared, strict=True):
            misplaced = {
                k: v
                for k, v in (c.neutralized_identifiers or {}).items()
                if v == IdentifierNeutralization.MISPLACED
            }
            after = {**misplaced, **(shared_map or {})} or None
            if after != c.neutralized_identifiers:
                changes.append({"id": c.id, "neutralized": cast("JsonValue", after)})
    if changes:
        conn.execute(
            text("""
                UPDATE source_contributions sc SET neutralized_identifiers = t.neutralized
                FROM jsonb_to_recordset(:payload) AS t(id integer, neutralized jsonb)
                WHERE sc.id = t.id
            """).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": changes},
        )
    return len(changes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        result = plan(fetch_rows(conn))
        log.info(
            "lignes mises à jour : %d, fusionnées : %d, à valeur modifiée : %d, valeurs mal formées écartées : %s",
            len(result.updates),
            len(result.merges),
            len(result.changed_values),
            dict(result.malformed),
        )
        if args.dry_run:
            conn.rollback()
            return 0
        changed = apply(conn, result)
        conn.commit()
        log.info("contributions sources à neutralisations modifiées : %d", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
