#!/usr/bin/env python3
"""One-shot : purge les doublons de position WoS + source_persons legacy.

Contexte
--------
~388 000 ``source_authorships`` WoS en double sur
``(source_publication_id, author_position)``, concentrés sur ~2200
méga-publis consortium (ATLAS/CERN, 5000+ auteurs). WoS renvoie parfois
deux entrées ``name`` au même ``seq_no`` pour un même auteur : une avec
``daisng_id`` renseigné et une sans. Pour ~98 % des groupes, la seconde
est un résidu d'un ancien code qui créait un ``source_id`` synthétique
``wos-XXXX`` ; le code actuel skip explicitement ce cas
(``if not daisng_id: continue``), mais les rows historiques subsistent.

Ce script applique le même cleanup que le ``post_process`` du
``WosNormalizer`` (``delete_wos_duplicate_authorships`` +
``delete_wos_orphan_legacy_source_persons``) en dehors d'un run pipeline
complet. Au prochain ``normalize`` WoS ces fonctions seront appelées
automatiquement — ce one-shot sert à purger le stock existant sans
attendre.

Usage
-----
    python -m interfaces.cli.cleanup_wos_duplicate_authorships --dry-run
    python -m interfaces.cli.cleanup_wos_duplicate_authorships
"""

from __future__ import annotations

import argparse
import logging
import os

from infrastructure.db.connection import get_connection
from infrastructure.db.queries.normalize_wos import PgWosNormalizeQueries
from infrastructure.log import setup_logger

log = setup_logger("cleanup_wos_duplicate_authorships", os.path.dirname(__file__))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge des doublons de position WoS + source_persons legacy"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compte sans modifier (rollback final)",
    )
    args = parser.parse_args()

    queries = PgWosNormalizeQueries()
    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()

        n_dups = queries.delete_wos_duplicate_authorships(cur)
        log.info("source_authorships doublons supprimés : %d", n_dups)

        n_orphans = queries.delete_wos_orphan_legacy_source_persons(cur)
        log.info("source_persons legacy orphelins supprimés : %d", n_orphans)

        if args.dry_run:
            log.info("[DRY RUN] rollback.")
            conn.rollback()
        else:
            conn.commit()
            log.info("Terminé.")

    except Exception:
        conn.rollback()
        logging.getLogger().exception("Échec — rollback effectué")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
