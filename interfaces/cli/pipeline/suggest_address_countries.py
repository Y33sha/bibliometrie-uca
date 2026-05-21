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

from sqlalchemy import Connection, text

from application.pipeline.metrics import PhaseMetrics
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.countries import suggest_addresses_countries_batch

logger = setup_logger("suggest_countries", "processing/logs")


def suggest_countries(
    conn: Connection,
    *,
    batch_size: int = 500,
    direct: bool = False,
    reset: bool = False,
    reset_empty: bool = False,
) -> PhaseMetrics:
    """Suggère des pays pour les adresses sans pays via match trigramme.

    Phase importable depuis `run_pipeline.py` ; ne ferme pas la connexion.
    Defaults pipeline : `direct=False` (écrit dans `suggested_countries`, confirmation manuelle attendue). `total` = adresses traitées, `new` = nb d'adresses pour lesquelles une suggestion a été trouvée.

    `reset` : remet à NULL toutes les suggestions (vides + non vides). Usage manuel.
    `reset_empty` : remet à NULL uniquement les suggestions vides (`= []`, adresses déjà tentées sans match). Activé par défaut en mode `full` du pipeline pour bénéficier d'une éventuelle évolution des heuristiques sans perdre les suggestions positives existantes.
    """
    target_column = "countries" if direct else "suggested_countries"

    if reset:
        with conn.begin():
            result = conn.execute(
                text("""
                    UPDATE addresses SET suggested_countries = NULL
                    WHERE countries IS NULL AND suggested_countries IS NOT NULL
                """)
            )
        logger.info(f"{result.rowcount} suggestions réinitialisées")
    elif reset_empty:
        with conn.begin():
            result = conn.execute(
                text("""
                    UPDATE addresses SET suggested_countries = NULL
                    WHERE countries IS NULL
                      AND suggested_countries IS NOT NULL
                      AND cardinality(suggested_countries) = 0
                """)
            )
        logger.info(f"{result.rowcount} suggestions vides réinitialisées (mode full)")

    counts = conn.execute(
        text("""
            SELECT
                COUNT(*) FILTER (
                    WHERE suggested_countries IS NULL AND length(normalized_text) >= 5
                ) AS eligible,
                COUNT(*) FILTER (WHERE cardinality(suggested_countries) > 0) AS has_suggestion,
                COUNT(*) FILTER (
                    WHERE suggested_countries IS NOT NULL
                      AND cardinality(suggested_countries) = 0
                ) AS empty_attempted,
                COUNT(*) FILTER (WHERE length(normalized_text) < 5) AS too_short
            FROM addresses
            WHERE countries IS NULL
        """)
    ).one()
    total = counts.eligible
    logger.info(
        f"{total} adresses à traiter (batch_size={batch_size}) — "
        f"{counts.has_suggestion} déjà avec suggestion, "
        f"{counts.empty_attempted} déjà tentées sans match, "
        f"{counts.too_short} trop courtes"
    )

    if total == 0:
        logger.info("Rien à faire.")
        return PhaseMetrics()

    processed = 0
    found = 0
    t0 = time.time()
    while True:
        n_done, n_found = suggest_addresses_countries_batch(
            conn, batch_size=batch_size, target_column=target_column
        )
        conn.commit()
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
    return PhaseMetrics(total=processed, new=found)


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

    with get_sync_engine().connect() as conn:
        suggest_countries(conn, batch_size=args.batch_size, direct=args.direct, reset=args.reset)


if __name__ == "__main__":
    main()
