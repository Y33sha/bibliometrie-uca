# STATUS: oneshot (2026-09-15)
"""Normalise les ISSN du stock de revues avec le value object `ISSN`.

Chaque valeur de `journals.issn`, `eissn` et `issnl` prend la forme `NNNN-NNNC`. Une valeur invalide est remplacée par NULL et journalisée. Le script compte aussi les ISSN portés par plusieurs revues après normalisation. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_normalize_journal_issns            # exécution
    python -m interfaces.cli.oneshot.backfill_normalize_journal_issns --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict

from sqlalchemy import Connection, text

from domain.publications.identifiers import ISSN
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_normalize_journal_issns", os.path.dirname(__file__))

_COLUMNS = ("issn", "eissn", "issnl")


def _normalize_stock(conn: Connection, apply: bool) -> None:
    rows = conn.execute(
        text(
            "SELECT id, title, issn, eissn, issnl FROM journals "
            "WHERE coalesce(issn, eissn, issnl) IS NOT NULL ORDER BY id"
        )
    ).all()
    updates: list[dict[str, object]] = []
    journals_by_issn: dict[str, set[int]] = defaultdict(set)
    rejected = 0
    for r in rows:
        normalized: dict[str, str | None] = {}
        for column in _COLUMNS:
            raw = getattr(r, column)
            issn = ISSN.try_parse(raw)
            if raw is not None and issn is None:
                log.info("écarté (revue %d, %r) : %s = %r", r.id, r.title, column, raw)
                rejected += 1
            normalized[column] = str(issn) if issn else None
            if issn:
                journals_by_issn[str(issn)].add(r.id)
        if any(normalized[c] != getattr(r, c) for c in _COLUMNS):
            updates.append({"id": r.id, **normalized})
    shared = [ids for ids in journals_by_issn.values() if len(ids) > 1]
    log.info("Valeurs écartées : %d", rejected)
    log.info("Revues à réécrire : %d / %d", len(updates), len(rows))
    log.info(
        "ISSN portés par plusieurs revues après normalisation : %d (%d revues)",
        len(shared),
        len(set().union(*shared)) if shared else 0,
    )
    if apply and updates:
        conn.execute(
            text("UPDATE journals SET issn = :issn, eissn = :eissn, issnl = :issnl WHERE id = :id"),
            updates,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    apply = not args.dry_run

    if not apply:
        log.info("DRY-RUN (rapport seul) — retirer --dry-run pour écrire")

    engine = get_sync_engine()
    with engine.connect() as conn:
        _normalize_stock(conn, apply)
        if apply:
            conn.commit()
            log.info("✓ backfill appliqué")
        else:
            log.info("DRY-RUN terminé — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
