"""
Nettoyage des idHAL mal assignés dans la table authors.

Le bug : authIdHal_s et authOrcid_s de l'API HAL sont des tableaux sparse
(ne contenant que les valeurs non-vides). L'ancien code les indexait par
position d'auteur, ce qui assignait les identifiants aux mauvaises personnes.

Ce script :
1. Remet à NULL tous les idhal dans authors (ils viennent tous de HAL, potentiellement faux)
2. Remet à NULL les orcid qui n'existent QUE via HAL (ceux aussi présents via OpenAlex sont fiables)
3. Affiche un résumé

Ensuite, relancer normalize_hal.py --reset pour réassigner correctement.

Usage:
    python cleanup_idhal.py              # exécuter le nettoyage
    python cleanup_idhal.py --dry-run    # voir ce qui serait nettoyé
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Nettoyage idHAL corrompus")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Diagnostique avant nettoyage
    cur.execute("SELECT COUNT(*) FROM authors WHERE idhal IS NOT NULL")
    idhal_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM authors WHERE orcid IS NOT NULL")
    orcid_count = cur.fetchone()[0]

    # Auteurs dont l'ORCID vient AUSSI d'OpenAlex (fiable)
    cur.execute("""
        SELECT COUNT(DISTINCT a.id)
        FROM authors a
        WHERE a.orcid IS NOT NULL
          AND a.openalex_id IS NOT NULL
    """)
    orcid_from_oa = cur.fetchone()[0]

    # Auteurs dont l'ORCID vient UNIQUEMENT de HAL (possiblement faux)
    orcid_hal_only = orcid_count - orcid_from_oa

    logger.info(f"=== État actuel ===")
    logger.info(f"  Auteurs avec idHAL   : {idhal_count} (tous potentiellement faux)")
    logger.info(f"  Auteurs avec ORCID   : {orcid_count}")
    logger.info(f"    - confirmés par OpenAlex : {orcid_from_oa} (fiables)")
    logger.info(f"    - HAL uniquement         : {orcid_hal_only} (potentiellement faux)")

    if args.dry_run:
        logger.info("\n(dry-run, pas de modification)")
        cur.close()
        conn.close()
        return

    # 1. Effacer TOUS les idHAL
    cur.execute("UPDATE authors SET idhal = NULL WHERE idhal IS NOT NULL")
    cleared_idhal = cur.rowcount
    logger.info(f"\n  idHAL effacés : {cleared_idhal}")

    # 2. Effacer les ORCID qui viennent uniquement de HAL (pas confirmés par OpenAlex)
    cur.execute("""
        UPDATE authors SET orcid = NULL
        WHERE orcid IS NOT NULL
          AND openalex_id IS NULL
    """)
    cleared_orcid = cur.rowcount
    logger.info(f"  ORCID HAL-only effacés : {cleared_orcid}")

    conn.commit()

    # Vérification
    cur.execute("SELECT COUNT(*) FROM authors WHERE idhal IS NOT NULL")
    logger.info(f"\n=== Après nettoyage ===")
    logger.info(f"  Auteurs avec idHAL : {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM authors WHERE orcid IS NOT NULL")
    logger.info(f"  Auteurs avec ORCID : {cur.fetchone()[0]}")

    logger.info(f"\n→ Relancer : python processing/normalize_hal.py --reset")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
