# STATUS: oneshot (2026-10-18)
"""Ajoute le rôle `author` aux signatures HAL et scanR du stock dont la qualité source est `ctb`, comme le fait la normalisation (`map_role`).

Le stock garde le seul rôle canonique `contributor`, commun à plusieurs qualités source (`ctb`, `sad`, `ill`…). Le oneshot relit donc le payload de chaque notice concernée dans le raw store et recalcule les rôles de ses signatures avec les fonctions de la normalisation. Une signature `[contributor]` reçoit les rôles recalculés à sa position quand ils comprennent `author`.

Les décomptes d'auteurs des notices touchées sont recalculés et leurs publications sont à regrouper. Un commit par lot de notices.

Usage :
    python -m interfaces.cli.oneshot.add_author_role_to_contributors [--dry-run] [--batch 500]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from collections.abc import Callable, Mapping

from sqlalchemy import Connection, text

from domain.publications.contribution_roles import ContributionRole
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from interfaces.cli.oneshot.backfill_author_counts import backfill_source_records
from pipeline.ingestion.common.source_contributions import AuthorRecord
from pipeline.ingestion.hal.normalize import build_hal_author_records
from pipeline.ingestion.scanr.normalize import build_scanr_author_records

log = setup_logger("add_author_role_to_contributors", os.path.dirname(__file__))

_BUILDERS: dict[str, Callable[[Mapping[str, JsonValue]], list[AuthorRecord]]] = {
    "hal": build_hal_author_records,
    "scanr": build_scanr_author_records,
}

# (signature, position) des signatures `[contributor]`, par notice (identifiant, source, identifiant source).
_CANDIDATES = f"""
    SELECT sr.id AS source_record, sr.source, sr.source_id, sc.id AS source_contribution, sc.author_position AS position
    FROM source_contributions sc JOIN source_records sr ON sr.id = sc.source_record_id
    WHERE sr.source IN ('hal', 'scanr') AND sc.roles = ARRAY['{ContributionRole.CONTRIBUTOR.value}']
    ORDER BY sr.id
"""  # noqa: S608

PayloadLoader = Callable[[str, str], Mapping[str, JsonValue] | None]


def raw_store_loader() -> PayloadLoader:
    """Lecture du payload d'une notice dans le raw store ; None s'il manque ou est illisible."""
    store = get_raw_store()

    def load(source: str, source_id: str) -> Mapping[str, JsonValue] | None:
        try:
            return json.loads(store.get(source, source_id))
        except (KeyError, UnreadablePayloadError):
            return None

    return load


def author_roles(
    source: str, payload: Mapping[str, JsonValue], positions: list[int | None]
) -> dict[int, list[str]]:
    """Rôles recalculés aux `positions` qui comprennent `author`."""
    by_position = {r.position: r.roles for r in _BUILDERS[source](payload)}
    return {
        p: [str(role) for role in roles]
        for p in positions
        if p is not None and (roles := by_position.get(p)) and ContributionRole.AUTHOR in roles
    }


def complete_source_records(
    conn: Connection, candidates: list[Mapping[str, object]], load: PayloadLoader
) -> tuple[int, int]:
    """Complète les rôles des signatures de ces notices. Rend (signatures complétées, payloads manquants)."""
    by_source_record: dict[tuple[int, str, str], list[tuple[int, int | None]]] = defaultdict(list)
    for c in candidates:
        by_source_record[(c["source_record"], c["source"], c["source_id"])].append(
            (c["source_contribution"], c["position"])
        )

    updates: list[dict[str, object]] = []
    touched: list[int] = []
    missing = 0
    for (source_record, source, source_id), source_contributions in by_source_record.items():
        payload = load(source, source_id)
        if payload is None:
            missing += 1
            continue
        roles = author_roles(source, payload, [p for _, p in source_contributions])
        new = [{"id": s, "roles": roles[p]} for s, p in source_contributions if p in roles]
        if new:
            updates.extend(new)
            touched.append(source_record)
    if updates:
        conn.execute(text("UPDATE source_contributions SET roles = :roles WHERE id = :id"), updates)
        backfill_source_records(conn, touched)
        conn.execute(
            text("""
                UPDATE publications p SET contributions_dirty = true
                FROM source_records sr
                WHERE sr.id = ANY(:source_records) AND p.id = sr.publication_id AND NOT p.contributions_dirty
            """),
            {"source_records": touched},
        )
    return len(updates), missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    parser.add_argument("--batch", type=int, default=500, help="nombre de notices par lot")
    args = parser.parse_args()

    completed = missing = 0
    load = raw_store_loader()
    with get_sync_engine().connect() as conn:
        candidates = [dict(r) for r in conn.execute(text(_CANDIDATES)).mappings()]
        source_records = sorted({c["source_record"] for c in candidates})
        log.info("notices à examiner : %d", len(source_records))
        for i in range(0, len(source_records), args.batch):
            batch = set(source_records[i : i + args.batch])
            done, lost = complete_source_records(
                conn, [c for c in candidates if c["source_record"] in batch], load
            )
            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()
            completed += done
            missing += lost
        log.info(
            "signatures %s : %d ; payloads manquants : %d",
            "à compléter" if args.dry_run else "complétées",
            completed,
            missing,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
