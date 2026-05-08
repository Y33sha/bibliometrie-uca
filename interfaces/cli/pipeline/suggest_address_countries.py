"""
Suggestion de pays pour les adresses restantes (sans pays après detect).

Pour chaque adresse sans pays, cherche les adresses AVEC pays dont le texte
normalisé la contient comme sous-chaîne (LIKE). Stocke les pays trouvés
dans addresses.suggested_countries.

Se lance après detect_address_countries.py pour rattraper les cas où le
pays n'apparaît pas en fin de chaîne.

Implémentation : un UPDATE bulk SQL par batch (CTE + UPDATE) qui exploite
l'index trigramme `idx_addresses_normalized_text_trgm` (migration 020).
Avant cette refonte : ~1 requête SQL par adresse + round-trip Python →
plusieurs heures pour ~8k adresses ; désormais : minutes.

Usage:
    python interfaces/cli/pipeline/suggest_address_countries.py
    python interfaces/cli/pipeline/suggest_address_countries.py --direct       # écrire dans countries
    python interfaces/cli/pipeline/suggest_address_countries.py --reset        # remettre à NULL
    python interfaces/cli/pipeline/suggest_address_countries.py --batch-size 200
"""

import argparse
import time

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queries.countries import suggest_addresses_countries_batch
from infrastructure.log import setup_logger

logger = setup_logger("suggest_countries", "processing/logs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--direct", action="store_true", help="Écrire dans countries au lieu de suggested_countries"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remettre à NULL les suggested_countries avant de relancer",
    )
    args = parser.parse_args()

    target_column = "countries" if args.direct else "suggested_countries"

    engine = get_sync_engine()
    with engine.connect() as conn:
        if args.reset:
            with conn.begin():
                result = conn.execute(
                    text("""
                        UPDATE addresses SET suggested_countries = NULL
                        WHERE countries IS NULL AND suggested_countries IS NOT NULL
                    """)
                )
            logger.info(f"{result.rowcount} suggestions réinitialisées")

        total = conn.execute(
            text("""
                SELECT COUNT(*) AS n FROM addresses
                WHERE countries IS NULL
                  AND suggested_countries IS NULL
                  AND length(normalized_text) >= 5
            """)
        ).scalar_one()
        logger.info(f"{total} adresses à traiter (batch_size={args.batch_size})")

        if total == 0:
            logger.info("Rien à faire.")
            return

        processed = 0
        found = 0
        t0 = time.time()
        while True:
            with conn.begin():
                n_done, n_found = suggest_addresses_countries_batch(
                    conn, batch_size=args.batch_size, target_column=target_column
                )
            if n_done == 0:
                break
            processed += n_done
            found += n_found
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = (total - processed) / rate if rate > 0 else 0
            logger.info(
                f"  {processed}/{total} traités "
                f"({found} avec suggestion, {elapsed:.0f}s, ~{remaining:.0f}s restantes)"
            )

        elapsed = time.time() - t0
        logger.info(f"\nTerminé : {processed} traitées, {found} avec suggestion, en {elapsed:.0f}s")


if __name__ == "__main__":
    main()
