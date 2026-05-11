"""
Détection automatique des pays des adresses via country_name_forms.

Parse le dernier segment (après la dernière virgule) de chaque adresse
sans pays et le matche contre la table country_name_forms.

Deux modes :
  - suggest : peuple addresses.suggested_countries (validation manuelle)
  - apply   : peuple directement addresses.countries (confiance élevée)

Usage:
    python interfaces/cli/pipeline/detect_address_countries.py                  # suggest (dry-run)
    python interfaces/cli/pipeline/detect_address_countries.py --apply          # appliquer les suggestions
    python interfaces/cli/pipeline/detect_address_countries.py --direct         # écrire directement dans countries
    python interfaces/cli/pipeline/detect_address_countries.py --direct --apply # appliquer direct
    python interfaces/cli/pipeline/detect_address_countries.py --stats          # statistiques uniquement
"""

import argparse
from collections import Counter

from sqlalchemy import Connection, bindparam, select, text, update

from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.tables import addresses, country_name_forms
from infrastructure.log import setup_logger

logger = setup_logger("suggest_countries", "processing/logs")


def load_country_forms(conn: Connection) -> dict[str, str]:
    """Charge country_name_forms. Retourne {form_normalized: iso_code}."""
    stmt = select(country_name_forms.c.form_normalized, country_name_forms.c.iso_code)
    return {r.form_normalized: r.iso_code for r in conn.execute(stmt)}


def extract_last_segment(raw_text: str) -> str:
    """Extrait et normalise le dernier segment après la dernière virgule."""
    parts = raw_text.rsplit(",", 1)
    if len(parts) < 2:
        return normalize_text(raw_text.strip())
    return normalize_text(parts[-1].strip())


def show_stats(conn: Connection) -> None:
    # count(*) FILTER (...) : reste en text() (peu lisible en SA Core)
    row = conn.execute(
        text("""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE countries IS NOT NULL) AS avec_pays,
                   count(*) FILTER (WHERE countries IS NULL AND suggested_countries IS NOT NULL
                                    AND array_length(suggested_countries, 1) > 0) AS avec_suggestion,
                   count(*) FILTER (WHERE countries IS NULL AND suggested_countries IS NULL) AS sans_rien
            FROM addresses WHERE pub_count > 0
        """)
    ).one()
    logger.info("Adresses (pub_count > 0) :")
    logger.info(f"  Total            : {row.total}")
    logger.info(f"  Avec pays        : {row.avec_pays}")
    logger.info(f"  Avec suggestion  : {row.avec_suggestion}")
    logger.info(f"  Sans rien        : {row.sans_rien}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Détection pays des adresses")
    parser.add_argument("--apply", action="store_true", help="Appliquer (sinon dry-run)")
    parser.add_argument(
        "--direct", action="store_true", help="Écrire dans countries au lieu de suggested_countries"
    )
    parser.add_argument("--stats", action="store_true", help="Stats uniquement")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        if args.stats:
            show_stats(conn)
            return

        country_forms = load_country_forms(conn)
        logger.info(f"{len(country_forms)} formes de noms de pays chargées")

        # Récupérer les adresses sans pays
        rows = conn.execute(
            select(addresses.c.id, addresses.c.raw_text).where(addresses.c.countries.is_(None))
        ).all()
        logger.info(f"{len(rows)} adresses sans pays")

        matched = 0
        unmatched = 0
        updates: list[tuple[int, str]] = []

        for r in rows:
            last_seg = extract_last_segment(r.raw_text)
            if not last_seg:
                unmatched += 1
                continue
            iso = country_forms.get(last_seg)
            if iso:
                updates.append((r.id, iso))
                matched += 1
            else:
                unmatched += 1

        logger.info(f"Matchés : {matched}, non matchés : {unmatched}")

        if not args.apply:
            unknown: Counter[str] = Counter()
            for r in rows:
                last_seg = extract_last_segment(r.raw_text)
                if last_seg and last_seg not in country_forms:
                    unknown[last_seg] += 1
            logger.info("\nTop 20 formes non reconnues :")
            for form, cnt in unknown.most_common(20):
                logger.info(f"  {cnt:>5}  {form}")
            logger.info("\nDry-run — ajouter --apply pour appliquer.")
            return

        # Appliquer (transaction unique, commit en fin de boucle)
        column = addresses.c.countries if args.direct else addresses.c.suggested_countries
        # executemany SA : un seul stmt paramétré + liste de dicts
        stmt = (
            update(addresses)
            .where(addresses.c.id == bindparam("addr_id"))
            .values({column: bindparam("val")})
        )
        for i in range(0, len(updates), 5000):
            batch = updates[i : i + 5000]
            conn.execute(
                stmt,
                [{"addr_id": addr_id, "val": [iso.lower()]} for addr_id, iso in batch],
            )
        conn.commit()

        logger.info(f"{matched} adresses mises à jour ({column.name})")
        show_stats(conn)


if __name__ == "__main__":
    main()
