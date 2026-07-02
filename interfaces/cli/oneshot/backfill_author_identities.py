# STATUS: oneshot (2026-07-02)
"""Backfill des identités d'auteur : peuple `author_identifying_keys` et pose `source_authorships.identity_id`.

Étape de données de la séparation de `source_authorships` (identité d'auteur ⊥ liaison), à lancer après la migration qui crée la table `author_identifying_keys` et la colonne nullable `identity_id`. Deux temps :

1. **Peuplement des identités** — un `INSERT … SELECT DISTINCT (author_name_normalized, person_identifiers) FROM source_authorships ON CONFLICT DO NOTHING`. Le `DISTINCT` collapse les ~19 M signatures sur les ~645 k identités distinctes ; `ON CONFLICT` rend l'étape idempotente (ré-exécution = no-op). Une seule requête, un seul commit.

2. **Pose de `identity_id`** — un `UPDATE … FROM author_identifying_keys` fenêtré par plage de `source_publication_id` (dense, portée par l'unique `(source_publication_id, author_position)`), commit par fenêtre pour ne pas tenir une transaction de 19 M lignes. Le filtre `identity_id IS NULL` rend l'étape résumable et idempotente. Le rapprochement se fait par `IS NOT DISTINCT FROM` sur les deux colonnes : une signature dont le nom ou les identifiants sont `NULL` doit matcher l'identité correspondante, cohérent avec l'unique `NULLS NOT DISTINCT` de la table d'identités (un simple `=` laisserait ces signatures sans identité).

Chaque signature a exactement une identité (la table est le jeu des couples distincts), donc le rapprochement est un 1:1. Ne touche ni `person_id`, ni les deux colonnes d'origine, qui restent en place jusqu'à la phase de contraction.

Usage :
    python -m interfaces.cli.oneshot.backfill_author_identities [--dry-run] [--window 2000] [--resume-from 0]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_author_identities", os.path.dirname(__file__))

_POPULATE_SQL = text("""
    INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers)
    SELECT DISTINCT author_name_normalized, person_identifiers
    FROM source_authorships
    ON CONFLICT (author_name_normalized, person_identifiers) DO NOTHING
""")

_MAX_PUB_SQL = text("SELECT max(source_publication_id) FROM source_authorships")

_REMAINING_SQL = text("SELECT count(*) FROM source_authorships WHERE identity_id IS NULL")

_LINK_WINDOW_SQL = text("""
    UPDATE source_authorships sa
    SET identity_id = aik.id
    FROM author_identifying_keys aik
    WHERE sa.source_publication_id > :last
      AND sa.source_publication_id <= :hi
      AND sa.identity_id IS NULL
      AND aik.author_name_normalized IS NOT DISTINCT FROM sa.author_name_normalized
      AND aik.person_identifiers IS NOT DISTINCT FROM sa.person_identifiers
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans écrire.")
    parser.add_argument(
        "--window", type=int, default=2000, help="Largeur de la fenêtre d'ids de publication."
    )
    parser.add_argument(
        "--resume-from", type=int, default=0, help="Reprendre après ce source_publication_id."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        remaining = conn.execute(_REMAINING_SQL).scalar() or 0
        log.info("Signatures sans identité : %d", remaining)

        if args.dry_run:
            log.info("Dry-run : aucune écriture. %d signatures seraient rattachées.", remaining)
            return 0

        # 1. Peuplement des identités (une requête, idempotente).
        log.info("Peuplement de author_identifying_keys (SELECT DISTINCT)…")
        conn.execute(_POPULATE_SQL)
        conn.commit()
        n_identities = conn.execute(text("SELECT count(*) FROM author_identifying_keys")).scalar()
        log.info("  %d identités distinctes en base.", n_identities)

        # 2. Pose de identity_id, fenêtrée et commit par fenêtre.
        max_pub = conn.execute(_MAX_PUB_SQL).scalar() or 0
        last = args.resume_from
        linked = 0
        while last < max_pub:
            hi = last + args.window
            result = conn.execute(_LINK_WINDOW_SQL, {"last": last, "hi": hi})
            conn.commit()
            linked += result.rowcount
            last = hi
            if (last // args.window) % 50 == 0:
                log.info("… curseur=%d/%d, %d signatures rattachées", last, max_pub, linked)

    log.info("Terminé : %d signatures rattachées à leur identité.", linked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
