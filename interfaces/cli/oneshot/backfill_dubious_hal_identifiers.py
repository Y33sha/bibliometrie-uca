# STATUS: oneshot (2026-06-19)
"""Backfill : marque `_dubious` les identifiants des signatures HAL à compte dupliqué.

Le `normalize` suffixe désormais `_dubious` à tous les identifiants d'une signature
dont le `hal_person_id` est listé sur ≥2 auteurs du même dépôt (erreur de saisie HAL :
le même compte ne devrait jamais apparaître deux fois). Les `source_authorships` déjà
en base portent encore les clés nues — ce one-shot applique le même renommage au stock,
sans re-normaliser tout HAL.

Détection identique au normalize : `hal_person_id` dupliqué au sein d'un même
`source_publication_id`. Pour chaque signature concernée, toutes les clés de
`person_identifiers` (hal_person_id/idref/idhal/orcid — attachées au compte HAL, donc
toutes douteuses) sont renommées `<clé>_dubious`. Valeurs conservées (réversible,
diagnosticable) mais écartées du matching personnes, qui lit les clés nues.

Idempotent : une fois renommée, `hal_person_id` n'existe plus comme clé nue → la
signature n'est plus re-sélectionnée.

Ne touche PAS aux `source_authorships.person_id` déjà posés (signatures erronées déjà
rattachées) ni à `person_identifiers` (identifiants déjà propagés) : ces nettoyages
relèvent d'un audit séparé.

Usage :
    python -m interfaces.cli.oneshot.backfill_dubious_hal_identifiers [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_dubious_hal_identifiers", os.path.dirname(__file__))

# Signatures dont le `hal_person_id` est dupliqué dans leur dépôt (même
# `source_publication_id`). `->>'hal_person_id' IS NOT NULL` plutôt que l'opérateur
# jsonb `?` (interprété comme un bind par SQLAlchemy `text()`).
_DUBIOUS_SIGNATURES_SQL = text("""
    WITH dup AS (
        SELECT source_publication_id, person_identifiers->>'hal_person_id' AS hpid
        FROM source_authorships
        WHERE source = 'hal' AND person_identifiers->>'hal_person_id' IS NOT NULL
        GROUP BY source_publication_id, person_identifiers->>'hal_person_id'
        HAVING count(*) >= 2
    )
    SELECT sa.id, sa.person_identifiers
    FROM source_authorships sa
    JOIN dup ON dup.source_publication_id = sa.source_publication_id
            AND sa.person_identifiers->>'hal_person_id' = dup.hpid
""")


def _mark_dubious(identifiers: dict) -> dict:
    """Suffixe `_dubious` à chaque clé non encore suffixée (réversible, idempotent)."""
    return {(k if k.endswith("_dubious") else f"{k}_dubious"): v for k, v in identifiers.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte les signatures concernées et sort."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(_DUBIOUS_SIGNATURES_SQL).all()
        log.info("%d signatures HAL à compte dupliqué (identifiants à marquer dubious)", len(rows))

        if args.dry_run:
            log.info("DRY-RUN : aucune écriture")
            return 0

        updates = [
            {"id": r.id, "ids": json.dumps(_mark_dubious(r.person_identifiers))} for r in rows
        ]
        if updates:
            conn.execute(
                text(
                    "UPDATE source_authorships SET person_identifiers = CAST(:ids AS jsonb) "
                    "WHERE id = :id"
                ),
                updates,
            )
            conn.commit()
        log.info("✓ %d signatures mises à jour", len(updates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
