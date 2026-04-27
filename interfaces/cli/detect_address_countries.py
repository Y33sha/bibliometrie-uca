"""
Détection automatique des pays des adresses via country_name_forms.

Parse le dernier segment (après la dernière virgule) de chaque adresse
sans pays et le matche contre la table country_name_forms.

Deux modes :
  - suggest : peuple addresses.suggested_countries (validation manuelle)
  - apply   : peuple directement addresses.countries (confiance élevée)

Usage:
    python scripts/suggest_address_countries.py                  # suggest (dry-run)
    python scripts/suggest_address_countries.py --apply          # appliquer les suggestions
    python scripts/suggest_address_countries.py --direct         # écrire directement dans countries
    python scripts/suggest_address_countries.py --direct --apply # appliquer direct
    python scripts/suggest_address_countries.py --stats          # statistiques uniquement
"""

import argparse
from typing import Any

from psycopg.rows import tuple_row

from domain.normalize import normalize_text
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

logger = setup_logger("suggest_countries", "processing/logs")


def load_country_forms(cur: Any) -> dict[str, str]:
    """Charge country_name_forms. Retourne {form_normalized: iso_code}."""
    cur.execute("SELECT form_normalized, iso_code FROM country_name_forms")
    return {r[0]: r[1] for r in cur.fetchall()}


def extract_last_segment(raw_text: str) -> str:
    """Extrait et normalise le dernier segment après la dernière virgule."""
    parts = raw_text.rsplit(",", 1)
    if len(parts) < 2:
        return normalize_text(raw_text.strip())
    return normalize_text(parts[-1].strip())


def show_stats(cur: Any) -> Any:
    cur.execute("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE countries IS NOT NULL) AS avec_pays,
               count(*) FILTER (WHERE countries IS NULL AND suggested_countries IS NOT NULL
                                AND array_length(suggested_countries, 1) > 0) AS avec_suggestion,
               count(*) FILTER (WHERE countries IS NULL AND suggested_countries IS NULL) AS sans_rien
        FROM addresses WHERE pub_count > 0
    """)
    r = cur.fetchone()
    logger.info("Adresses (pub_count > 0) :")
    logger.info(f"  Total            : {r[0]}")
    logger.info(f"  Avec pays        : {r[1]}")
    logger.info(f"  Avec suggestion  : {r[2]}")
    logger.info(f"  Sans rien        : {r[3]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Détection pays des adresses")
    parser.add_argument("--apply", action="store_true", help="Appliquer (sinon dry-run)")
    parser.add_argument(
        "--direct", action="store_true", help="Écrire dans countries au lieu de suggested_countries"
    )
    parser.add_argument("--stats", action="store_true", help="Stats uniquement")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor(row_factory=tuple_row)

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    country_forms = load_country_forms(cur)
    logger.info(f"{len(country_forms)} formes de noms de pays chargées")

    # Récupérer les adresses sans pays
    cur.execute("""
        SELECT id, raw_text FROM addresses
        WHERE countries IS NULL
    """)
    rows = cur.fetchall()
    logger.info(f"{len(rows)} adresses sans pays")

    matched = 0
    unmatched = 0
    updates = []

    for addr_id, raw_text in rows:
        last_seg = extract_last_segment(raw_text)
        if not last_seg:
            unmatched += 1
            continue

        iso = country_forms.get(last_seg)
        if iso:
            updates.append((addr_id, iso))
            matched += 1
        else:
            unmatched += 1

    logger.info(f"Matchés : {matched}, non matchés : {unmatched}")

    if not args.apply:
        # Afficher les formes non reconnues les plus fréquentes
        from collections import Counter

        unknown: Counter[str] = Counter()
        for _addr_id, raw_text in rows:
            last_seg = extract_last_segment(raw_text)
            if last_seg and last_seg not in country_forms:
                unknown[last_seg] += 1
        logger.info("\nTop 20 formes non reconnues :")
        for form, cnt in unknown.most_common(20):
            logger.info(f"  {cnt:>5}  {form}")
        logger.info("\nDry-run — ajouter --apply pour appliquer.")
        conn.close()
        return

    # Appliquer
    column = "countries" if args.direct else "suggested_countries"
    batch = []
    for addr_id, iso in updates:
        batch.append((addr_id, [iso.lower()]))
        if len(batch) >= 5000:
            _apply_batch(cur, batch, column)
            conn.commit()
            batch = []
    if batch:
        _apply_batch(cur, batch, column)
        conn.commit()

    logger.info(f"{matched} adresses mises à jour ({column})")
    show_stats(cur)
    conn.close()


def _apply_batch(cur: Any, batch: Any, column: Any) -> Any:
    cur.executemany(
        f"UPDATE addresses SET {column} = %s WHERE id = %s",
        [(countries, addr_id) for addr_id, countries in batch],
    )


if __name__ == "__main__":
    main()
