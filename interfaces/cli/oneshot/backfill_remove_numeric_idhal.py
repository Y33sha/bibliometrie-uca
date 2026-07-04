# STATUS: oneshot (2026-07-04)
"""Backfill : retire les IdHAL purement numériques (reliquats) des identités d'auteur.

Des `hal_person_id` figurant dans une balise `<idhal>` ont été importés en masse
autrefois, produisant de faux IdHAL numériques (== hal_person_id ré-étiqueté). Le
`normalize` ne les extrait plus (il ignore l'idno idhal `notation="numeric"`), mais des
`author_identifying_keys` déjà en base en portent encore. Ce one-shot les nettoie au stock.

Cible : identité dont `person_identifiers` porte une clé `idhal` **purement numérique**.
Un IdHAL slug (même contenant des chiffres, ex. `dupont-2`) n'est pas visé.

Retirer l'IdHAL change la clé d'identité `(author_name_normalized, person_identifiers)`.
L'opération est donc un **re-pointage** (comme `backfill_remove_wos_only_orcid`) : on résout
l'identité cible sans l'IdHAL numérique, on y déplace les signatures, puis on supprime
l'identité d'origine. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_remove_numeric_idhal [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_remove_numeric_idhal", os.path.dirname(__file__))

_COMMIT_EVERY = 200

_TARGETS_SQL = text("""
    SELECT aik.id, aik.author_name_normalized AS name, aik.person_identifiers AS ids
    FROM author_identifying_keys aik
    WHERE aik.person_identifiers ? 'idhal'
      AND (aik.person_identifiers ->> 'idhal') ~ '^[0-9]+$'
    ORDER BY aik.id
""")

_UPSERT_TARGET_SQL = text("""
    INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers)
    VALUES (:name, CAST(:ids AS jsonb)) ON CONFLICT DO NOTHING
""")

_FIND_TARGET_SQL = text("""
    SELECT id FROM author_identifying_keys
    WHERE author_name_normalized IS NOT DISTINCT FROM :name
      AND person_identifiers IS NOT DISTINCT FROM CAST(:ids AS jsonb)
""")

_REPOINT_SQL = text("UPDATE source_authorships SET identity_id = :tgt WHERE identity_id = :old")
_DELETE_OLD_SQL = text("DELETE FROM author_identifying_keys WHERE id = :old")


def _without_numeric_idhal(ids: dict) -> dict | None:
    """Retire la clé `idhal` si sa valeur est purement numérique ; `None` si le dict
    devient vide."""
    kept = {k: v for k, v in ids.items() if not (k == "idhal" and str(v).isdigit())}
    return kept or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="N'écrit rien : compte les identités visées."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        targets = conn.execute(_TARGETS_SQL).all()
        log.info("%d identités portant un IdHAL numérique.", len(targets))

        if args.dry_run:
            collapses = sum(1 for t in targets if _without_numeric_idhal(t.ids) is None)
            log.info(
                "(dry-run) dont %d s'effondreraient sur une identité purement nominale.",
                collapses,
            )
            return 0

        repointed = 0
        for t in targets:
            new_ids = _without_numeric_idhal(t.ids)
            ids_json = json.dumps(new_ids) if new_ids is not None else None
            conn.execute(_UPSERT_TARGET_SQL, {"name": t.name, "ids": ids_json})
            target_id = conn.execute(
                _FIND_TARGET_SQL, {"name": t.name, "ids": ids_json}
            ).scalar_one()
            conn.execute(_REPOINT_SQL, {"tgt": target_id, "old": t.id})
            conn.execute(_DELETE_OLD_SQL, {"old": t.id})
            repointed += 1
            if repointed % _COMMIT_EVERY == 0:
                conn.commit()
                log.info("  %d/%d identités re-pointées...", repointed, len(targets))

        conn.commit()
        log.info("Terminé : %d identités nettoyées de leur IdHAL numérique.", repointed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
