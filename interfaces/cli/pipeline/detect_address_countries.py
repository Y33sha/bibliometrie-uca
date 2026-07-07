"""
Détection automatique des pays des adresses via les noms de pays.

Parse le dernier segment (après la dernière virgule) de chaque adresse
sans pays et le matche contre les noms de pays de `place_name_forms`
(`kind = 'country'`). Les noms de pays sont détectés en fin de segment ;
les villes/institutions (`kind = 'place'`) relèvent d'une passe dédiée.

Deux colonnes cibles :
  - défaut   : peuple addresses.suggested_countries (validation manuelle)
  - --direct : peuple directement addresses.countries (confiance élevée)

Usage:
    python interfaces/cli/pipeline/detect_address_countries.py                   # écrit suggested_countries
    python interfaces/cli/pipeline/detect_address_countries.py --direct          # écrit directement countries
    python interfaces/cli/pipeline/detect_address_countries.py --dry-run         # aperçu, n'écrit rien
    python interfaces/cli/pipeline/detect_address_countries.py --stats           # statistiques uniquement
"""

import argparse
from collections import Counter

from sqlalchemy import Connection, select

from application.pipeline.metrics import PhaseMetrics
from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.tables import addresses, place_name_forms
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.countries import (
    count_address_country_status,
    write_countries,
)

logger = setup_logger("detect_countries", "processing/logs")


def load_country_forms(conn: Connection) -> dict[str, str]:
    """Charge les noms de pays (`place_name_forms`, `kind = 'country'`). Retourne {form_normalized: iso_code}."""
    stmt = select(place_name_forms.c.form_normalized, place_name_forms.c.iso_code).where(
        place_name_forms.c.kind == "country"
    )
    return {r.form_normalized: r.iso_code for r in conn.execute(stmt)}


def extract_last_segment(raw_text: str) -> str:
    """Extrait et normalise le dernier segment après la dernière virgule."""
    parts = raw_text.rsplit(",", 1)
    if len(parts) < 2:
        return normalize_text(raw_text.strip())
    return normalize_text(parts[-1].strip())


def show_stats(conn: Connection) -> None:
    """Affiche le bilan global (mode `--stats` du CLI). Dans le pipeline, le bilan
    est logué une fois en début et une fois en fin de phase, pas ici."""
    s = count_address_country_status(conn)
    logger.info("Adresses (pub_count > 0) :")
    logger.info(f"  Total            : {s.total}")
    logger.info(f"  Avec pays        : {s.with_country}")
    logger.info(f"  Avec suggestion  : {s.with_suggestion}")
    logger.info(f"  Sans rien        : {s.none}")


def detect_countries(
    conn: Connection,
    *,
    apply: bool = True,
    direct: bool = True,
    stats_only: bool = False,
) -> PhaseMetrics:
    """Détecte les pays des adresses via match du dernier segment.

    Phase importable depuis `run_pipeline.py` ; ne ferme pas la connexion
    (responsabilité du caller). Defaults pipeline : `apply=True direct=True`
    (écrit dans `countries`). `total` = adresses sans pays, `new` = matchées
    et écrites, `extras["unmatched"]` = sans correspondance.
    """
    if stats_only:
        show_stats(conn)
        return PhaseMetrics()

    country_forms = load_country_forms(conn)
    logger.info(f"{len(country_forms)} formes de noms de pays chargées")

    rows = conn.execute(
        select(addresses.c.id, addresses.c.raw_text).where(addresses.c.countries.is_(None))
    ).all()
    logger.info(f"{len(rows)} adresses sans pays")

    matched: list[tuple[int, str]] = []
    unmatched = 0
    for r in rows:
        last_seg = extract_last_segment(r.raw_text)
        if not last_seg:
            unmatched += 1
            continue
        iso = country_forms.get(last_seg)
        if iso:
            matched.append((r.id, iso))
        else:
            unmatched += 1

    logger.info(f"Matchés : {len(matched)}, non matchés : {unmatched}")

    if not apply:
        unknown: Counter[str] = Counter()
        for r in rows:
            last_seg = extract_last_segment(r.raw_text)
            if last_seg and last_seg not in country_forms:
                unknown[last_seg] += 1
        logger.info("\nTop 20 formes non reconnues :")
        for form, cnt in unknown.most_common(20):
            logger.info(f"  {cnt:>5}  {form}")
        logger.info("\nDry-run — retirer --dry-run pour appliquer.")
        return PhaseMetrics(seen=len(rows), extras={"unmatched": unmatched})

    target_column = "countries" if direct else "suggested_countries"
    # Écriture bulk ; en mode `countries`, `write_countries` pose aussi
    # `addresses.countries_dirty` → le refresh recalcule les sa liés.
    write_countries(
        conn, [(addr_id, [iso]) for addr_id, iso in matched], target_column=target_column
    )
    conn.commit()

    logger.info(f"{len(matched)} adresses mises à jour ({target_column})")
    return PhaseMetrics(seen=len(rows), new=len(matched), extras={"unmatched": unmatched})


def main() -> None:
    parser = argparse.ArgumentParser(description="Détection pays des adresses")
    parser.add_argument("--dry-run", action="store_true", help="Aperçu : n'écrit rien")
    parser.add_argument(
        "--direct", action="store_true", help="Écrire dans countries au lieu de suggested_countries"
    )
    parser.add_argument("--stats", action="store_true", help="Stats uniquement")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        detect_countries(conn, apply=not args.dry_run, direct=args.direct, stats_only=args.stats)


if __name__ == "__main__":
    main()
