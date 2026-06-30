"""
Suggestion de pays pour les adresses restantes (sans pays après detect).

Pour chaque adresse sans pays, cherche les adresses AVEC pays dont le texte
normalisé la contient comme sous-chaîne, et retient le ou les pays les plus
fréquents. Stocke dans addresses.suggested_countries (confirmation manuelle).

Se lance après detect_address_countries.py pour rattraper les cas où le pays
n'apparaît pas en fin de chaîne.

Implémentation : un automate Aho-Corasick inversé (cibles = motifs, pool =
textes) balayé en un seul passage, par batch de cibles pour borner la mémoire
(cf. application/pipeline/countries/suggest_countries.py). Remplace l'ancienne
recherche trigram par cible (une requête SQL par adresse, plusieurs heures sur
le stock complet ; désormais ~1-2 min).

Usage:
    python -m interfaces.cli.pipeline.suggest_address_countries
    python -m interfaces.cli.pipeline.suggest_address_countries --direct       # écrire dans countries
    python -m interfaces.cli.pipeline.suggest_address_countries --retry-empty   # réessayer les vides
    python -m interfaces.cli.pipeline.suggest_address_countries --batch-size 20000
"""

import argparse
import time

from sqlalchemy import Connection

from application.pipeline.countries.suggest_countries import CountrySuggester
from application.pipeline.metrics import PhaseMetrics
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.countries import (
    count_suggest_eligible,
    fetch_suggest_targets_chunk,
    load_country_pool,
    write_countries,
)

logger = setup_logger("suggest_countries", "processing/logs")

# Batch de cibles : l'automate, les compteurs et l'écriture sont bornés par
# cette taille ; le pool est rescanné une fois par batch. Grand par défaut —
# le coût d'un balayage du pool s'amortit sur tout le batch.
BATCH_SIZE = 50000


def suggest_countries(
    conn: Connection,
    *,
    batch_size: int = BATCH_SIZE,
    direct: bool = False,
    retry_empty: bool = False,
) -> PhaseMetrics:
    """Suggère des pays pour les adresses sans pays via automate Aho-Corasick inversé.

    Phase importable depuis `run_pipeline.py` ; ne ferme pas la connexion.
    Defaults pipeline : `direct=False` (écrit dans `suggested_countries`,
    confirmation manuelle attendue). `total` = adresses traitées, `new` = nb
    d'adresses pour lesquelles une suggestion a été trouvée.

    `retry_empty` (mode `full`) : traite les nouvelles **+ les vides** (échecs
    précédents `= []`), pour réessayer au cas où le pool aurait grossi — sans
    recalculer les suggestions positives (qui changent rarement et coûtent cher).
    Sinon (incrémental) : seulement les nouvelles (`suggested_countries IS NULL`).
    """
    target_column = "countries" if direct else "suggested_countries"

    counts = count_suggest_eligible(conn)
    total = counts.eligible + (counts.empty_attempted if retry_empty else 0)
    mode = "retry-vides" if retry_empty else "incrémental"
    logger.info(
        f"{total} adresses à traiter (mode {mode}, batch_size={batch_size}) — "
        f"{counts.has_suggestion} déjà avec suggestion, "
        f"{counts.empty_attempted} déjà tentées sans match, "
        f"{counts.too_short} trop courtes"
    )
    if total == 0:
        logger.info("Rien à faire.")
        return PhaseMetrics()

    logger.info("Chargement du pool (adresses avec pays)...")
    pool = load_country_pool(conn)
    logger.info(f"  {len(pool)} adresses dans le pool")

    processed = 0
    found = 0
    after_id = 0
    t0 = time.time()
    while True:
        targets = fetch_suggest_targets_chunk(
            conn, after_id=after_id, limit=batch_size, retry_empty=retry_empty
        )
        if not targets:
            break
        after_id = targets[-1][0]  # tranche triée par id

        suggestions = CountrySuggester(targets).suggest(pool)
        rows = [(addr_id, suggestions.get(addr_id, [])) for addr_id, _ in targets]
        write_countries(conn, rows, target_column=target_column)
        conn.commit()

        processed += len(targets)
        found += sum(1 for _, sug in rows if sug)
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (total - processed) / rate if rate > 0 else 0
        logger.info(
            f"  {processed}/{total} traités "
            f"({found} avec suggestion, {elapsed:.0f}s, ~{remaining:.0f}s restantes)"
        )

    elapsed = time.time() - t0
    logger.info(f"\nTerminé : {processed} traitées, {found} avec suggestion, en {elapsed:.0f}s")
    return PhaseMetrics(seen=processed, new=found)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument(
        "--direct", action="store_true", help="Écrire dans countries au lieu de suggested_countries"
    )
    parser.add_argument(
        "--retry-empty",
        action="store_true",
        help="Réessayer aussi les suggestions vides (sinon seulement les nouvelles)",
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        suggest_countries(
            conn, batch_size=args.batch_size, direct=args.direct, retry_empty=args.retry_empty
        )


if __name__ == "__main__":
    main()
