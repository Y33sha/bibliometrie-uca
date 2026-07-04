# STATUS: oneshot (2026-07-04)
"""Backfill : retire l'ORCID des identités référencées uniquement par des signatures WoS.

Le `normalize` ne moissonne plus l'ORCID WoS (attribué par le matching algorithmique
interne de Web of Science, trop peu fiable pour figurer sur l'identité d'auteur). Les
`author_identifying_keys` déjà en base peuvent encore porter un ORCID venu exclusivement
de signatures WoS ; ce one-shot les nettoie au stock.

Cible : identité dont **toutes** les signatures sont de source `wos` et dont
`person_identifiers` porte une clé `orcid` ou `orcid_dubious`. Un ORCID partagé avec une
signature non-WoS (même identité) est fiable et conservé — d'où le filtre « uniquement WoS ».

Retirer l'ORCID change la clé d'identité `(author_name_normalized, person_identifiers)`.
L'opération est donc un **re-pointage**, pas une mutation en place : on résout (crée ou
retrouve) l'identité cible sans ORCID, on y déplace les signatures, puis on supprime
l'identité d'origine devenue orpheline. Idempotent : un re-run ne trouve plus d'identité
WoS-seule portant un ORCID.

Usage :
    python -m interfaces.cli.oneshot.backfill_remove_wos_only_orcid [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_remove_wos_only_orcid", os.path.dirname(__file__))

_COMMIT_EVERY = 500

# Identités WoS-seules portant un ORCID (nu ou `_dubious`).
_TARGETS_SQL = text("""
    SELECT aik.id, aik.author_name_normalized AS name, aik.person_identifiers AS ids
    FROM author_identifying_keys aik
    WHERE (aik.person_identifiers ? 'orcid' OR aik.person_identifiers ? 'orcid_dubious')
      AND EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.identity_id = aik.id)
      AND NOT EXISTS (
          SELECT 1 FROM source_authorships sa
          WHERE sa.identity_id = aik.id AND sa.source <> 'wos'
      )
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


def _without_orcid(ids: dict) -> dict | None:
    """Retire toute clé ORCID (`orcid`, `orcid_dubious`) ; `None` si le dict devient vide."""
    kept = {k: v for k, v in ids.items() if not k.startswith("orcid")}
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
        log.info("%d identités WoS-seules portant un ORCID.", len(targets))

        if args.dry_run:
            collapses = sum(1 for t in targets if _without_orcid(t.ids) is None)
            log.info(
                "(dry-run) dont %d s'effondreraient sur une identité purement nominale "
                "(plus aucun identifiant après retrait de l'ORCID).",
                collapses,
            )
            return 0

        repointed = 0
        for t in targets:
            new_ids = _without_orcid(t.ids)
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
        log.info("Terminé : %d identités nettoyées de leur ORCID WoS.", repointed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
