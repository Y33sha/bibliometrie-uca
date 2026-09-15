# STATUS: oneshot (2026-09-15)
"""Normalise le stock de `source_publications.external_ids` avec la règle appliquée à l'écriture.

Chaque valeur passe par le value object de son type (`domain.source_publications.external_ids`). Une valeur invalide ou une clé hors de `ExternalIdType` est écartée et journalisée. Deux clés anciennes d'OpenAlex sont reprises avant la normalisation :

- `pmc` devient `pmcid` quand `pmcid` est absent ;
- `source_doi` rejoint `related_dois`, sauf s'il est le DOI de la ligne.

Une ligne dont une clé de confirmation change est marquée `keys_dirty` : la phase `publications` recalcule son rattachement. La copie de `external_ids` rangée dans `raw_metadata` par `metadata_correction` suit la même règle. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_normalize_external_ids            # exécution
    python -m interfaces.cli.oneshot.backfill_normalize_external_ids --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Mapping

from sqlalchemy import Connection, text

from domain.publications.identifiers import clean_doi
from domain.source_publications.external_ids import ExternalIdType, normalize_external_ids
from domain.source_publications.keys import CONFIRMATION_ID_TYPES
from domain.source_publications.raw_metadata import RAW
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_normalize_external_ids", os.path.dirname(__file__))

_LEGACY_PMCID = "pmc"
_LEGACY_RELATED_DOI = "source_doi"


def _migrate_legacy_keys(
    external_ids: Mapping[str, JsonValue], doi: str | None
) -> dict[str, JsonValue]:
    """Reprend les clés anciennes `pmc` et `source_doi` sous leur type."""
    out = dict(external_ids)
    pmc = out.pop(_LEGACY_PMCID, None)
    if pmc is not None and ExternalIdType.PMCID not in out:
        out[ExternalIdType.PMCID] = pmc
    source_doi = out.pop(_LEGACY_RELATED_DOI, None)
    if isinstance(source_doi, str) and clean_doi(source_doi) != doi:
        related = out.get(ExternalIdType.RELATED_DOIS)
        existing = related if isinstance(related, list) else [related] if related else []
        out[ExternalIdType.RELATED_DOIS] = [*existing, source_doi]
    return out


def _normalized(
    external_ids: Mapping[str, JsonValue], doi: str | None, label: str, rejections: Counter[str]
) -> dict[str, JsonValue]:
    """`external_ids` repris puis normalisé. Chaque entrée écartée est journalisée."""
    clean, rejected = normalize_external_ids(_migrate_legacy_keys(external_ids, doi))
    for entry in rejected:
        log.info("écarté (%s) : %s = %r", label, entry.key, entry.value)
        rejections[entry.key] += 1
    return clean


def _normalized_raw_metadata(
    raw_metadata: Mapping[str, JsonValue] | None,
    doi: str | None,
    label: str,
    rejections: Counter[str],
) -> Mapping[str, JsonValue] | None:
    """`raw_metadata` dont la copie de `external_ids` est normalisée."""
    if not raw_metadata:
        return raw_metadata
    entry = raw_metadata.get("external_ids")
    if not isinstance(entry, dict) or not isinstance(entry.get(RAW), dict):
        return raw_metadata
    stashed = _normalized(entry[RAW], doi, f"{label}, raw_metadata", rejections)
    return {**raw_metadata, "external_ids": {**entry, RAW: stashed}}


def _normalize_stock(conn: Connection, apply: bool) -> None:
    rows = conn.execute(
        text(
            "SELECT id, source::text AS source, source_id, doi, external_ids, raw_metadata "
            "FROM source_publications"
        )
    ).all()
    rejections: Counter[str] = Counter()
    updates: list[dict[str, object]] = []
    for r in rows:
        label = f"{r.source} {r.source_id}"
        clean = _normalized(r.external_ids, r.doi, label, rejections)
        raw_metadata = _normalized_raw_metadata(r.raw_metadata, r.doi, label, rejections)
        if clean == r.external_ids and raw_metadata == r.raw_metadata:
            continue
        updates.append(
            {
                "id": r.id,
                "ext": json.dumps(clean),
                "raw": json.dumps(raw_metadata) if raw_metadata is not None else None,
                "dirty": any(clean.get(k) != r.external_ids.get(k) for k in CONFIRMATION_ID_TYPES),
            }
        )
    log.info("Entrées écartées par clé : %s", dict(rejections))
    log.info(
        "source_publications à réécrire : %d / %d, dont %d marquées keys_dirty",
        len(updates),
        len(rows),
        sum(1 for u in updates if u["dirty"]),
    )
    if apply and updates:
        conn.execute(
            text(
                "UPDATE source_publications "
                "SET external_ids = CAST(:ext AS jsonb), raw_metadata = CAST(:raw AS jsonb), "
                "keys_dirty = keys_dirty OR :dirty "
                "WHERE id = :id"
            ),
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
