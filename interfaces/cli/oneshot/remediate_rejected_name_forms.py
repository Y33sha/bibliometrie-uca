# STATUS: oneshot
"""Détache rétrospectivement les signatures des formes de nom déjà rejetées.

Rejeter une forme pose le verrou (`person_name_forms.status = 'rejected'`). Depuis
l'intégration going-forward, le rejet via l'UI détache aussi ses `source_authorships`.
Ce script rattrape le **backlog** des formes rejetées AVANT cette intégration :

1. nulle les `source_authorships` portant une forme rejetée pour la personne concernée
   (`person_id` ← NULL) ;
2. supprime les `authorships` canoniques de ces personnes devenues sans source ;
3. recompute `person_name_forms` (le tombstone rejeté est préservé).

Les signatures détachées restent orphelines ; un run du pipeline (phase persons) les
ré-attribuera, le verrou empêchant le retour via la forme rejetée.

Usage :
    python -m interfaces.cli.oneshot.remediate_rejected_name_forms [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from application.pipeline.persons.populate_person_name_forms import populate
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.person_name_forms import PgPersonNameFormsQueries

log = setup_logger("remediate_rejected_name_forms", os.path.dirname(__file__))

_NULL_SQL = text("""
    UPDATE source_authorships sa SET person_id = NULL
    FROM person_name_forms pnf, author_identifying_keys aik
    WHERE aik.id = sa.identity_id
      AND pnf.person_id = sa.person_id
      AND pnf.name_form = aik.author_name_normalized
      AND pnf.status = 'rejected'
""")

# Authorships canoniques des personnes à formes rejetées, devenues sans aucune
# source_authorship (après le null) : à supprimer.
_DELETE_ORPHAN_AUTHORSHIPS_SQL = text("""
    DELETE FROM authorships a
    WHERE a.person_id IN (SELECT DISTINCT person_id FROM person_name_forms WHERE status = 'rejected')
      AND NOT EXISTS (
          SELECT 1 FROM source_authorships sa
          JOIN source_publications sd ON sd.id = sa.source_publication_id
          WHERE sa.person_id = a.person_id AND sd.publication_id = a.publication_id
      )
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="N'écrit rien : affiche les comptes et sort."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        n_forms = conn.execute(
            text("SELECT count(*) FROM person_name_forms WHERE status = 'rejected'")
        ).scalar_one()
        n_sa = conn.execute(
            text("""
                SELECT count(*) FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                JOIN person_name_forms pnf
                  ON pnf.person_id = sa.person_id
                 AND pnf.name_form = aik.author_name_normalized
                 AND pnf.status = 'rejected'
            """)
        ).scalar_one()

    log.info("Formes rejetées : %d", n_forms)
    log.info("  → source_authorships à détacher : %d", n_sa)

    if n_sa == 0:
        log.info("Rien à détacher.")
        return 0
    if args.dry_run:
        log.info("Dry-run : aucune écriture.")
        return 0

    with engine.begin() as conn:
        detached = conn.execute(_NULL_SQL).rowcount
        log.info("1/3 — source_authorships détachées : %d", detached)

        deleted = conn.execute(_DELETE_ORPHAN_AUTHORSHIPS_SQL).rowcount
        log.info("2/3 — authorships canoniques orphelines supprimées : %d", deleted)

        log.info("3/3 — recompute person_name_forms…")
        populate(conn, PgPersonNameFormsQueries(), log)

    log.info("✓ Terminé. Relancer le pipeline (phase persons) pour ré-attribuer les orphelines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
