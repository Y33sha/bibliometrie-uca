"""
Résolution des affiliations OpenAlex : identification UCA + rattachement labo.

Usage:
    python resolve_affiliations.py              # traiter toutes les affiliations non résolues
    python resolve_affiliations.py --limit 1000 # limiter pour test
    python resolve_affiliations.py --reset      # remettre à zéro les résolutions
    python resolve_affiliations.py --stats      # afficher les stats sans traiter

Stratégie d'optimisation :
    Plutôt que de valider chaque ligne publication_authors individuellement,
    on extrait les raw_affiliation DISTINCTES, on les valide une seule fois,
    puis on applique les résultats en batch. Ça réduit le nombre d'appels
    au validateur de ~2M à quelques dizaines de milliers.
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

# Import du validateur existant
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"))
from validator import SignatureValidator

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "resolve_affiliations.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

# Chemins vers les fichiers de config
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
LABOS_JSON = os.path.join(CONFIG_DIR, "labos.json")
CONFIG_JSON = os.path.join(CONFIG_DIR, "config_validation.json")


def build_ror_to_lab_id(cur) -> dict:
    """Construit le mapping ROR ID → laboratories.id."""
    cur.execute("SELECT id, ror_id FROM laboratories WHERE ror_id IS NOT NULL")
    return {row[1]: row[0] for row in cur.fetchall()}


def get_distinct_affiliations(cur, source: str = "openalex", limit: int = None) -> list:
    """
    Récupère les affiliations distinctes non encore résolues.
    Retourne une liste de raw_affiliation uniques.
    """
    query = """
        SELECT DISTINCT raw_affiliation
        FROM publication_authors
        WHERE source = %s
          AND raw_affiliation IS NOT NULL
          AND raw_affiliation != ''
          AND affiliation_resolved_at IS NULL
    """
    if limit:
        query += f" LIMIT {limit}"

    cur.execute(query, (source,))
    return [row[0] for row in cur.fetchall()]


def resolve_affiliation(validator: SignatureValidator, affiliation: str) -> dict:
    """
    Résout une affiliation via le validateur.
    Retourne un dict avec les résultats.
    """
    # L'affiliation peut contenir plusieurs chaînes séparées par " | "
    # (c'est comme ça qu'on les a stockées dans normalize_openalex)
    parts = affiliation.split(" | ")

    is_uca = False
    labo_ror = None
    labo_name = None
    confidence = 0.0

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Test UCA
        if validator.est_signature_uca(part):
            is_uca = True

            # Identification labo
            ror, name, conf = validator.identifier_laboratoire(part)
            if ror and conf > confidence:
                labo_ror = ror
                labo_name = name
                confidence = conf

    return {
        "is_uca": is_uca,
        "labo_ror": labo_ror,
        "labo_name": labo_name,
        "confidence": confidence,
    }


def apply_results(cur, affiliation: str, result: dict, ror_to_lab: dict, source: str = "openalex"):
    """
    Applique les résultats de résolution à toutes les lignes
    publication_authors ayant cette raw_affiliation.
    """
    lab_id = None
    if result["labo_ror"] and result["labo_ror"] in ror_to_lab:
        lab_id = ror_to_lab[result["labo_ror"]]

    cur.execute("""
        UPDATE publication_authors SET
            is_uca_author = %s,
            laboratory_id = COALESCE(%s, publication_authors.laboratory_id),
            affiliation_resolved_at = now()
        WHERE source = %s
          AND raw_affiliation = %s
          AND affiliation_resolved_at IS NULL
    """, (result["is_uca"], lab_id, source, affiliation))

    return cur.rowcount


def update_publication_validation(cur):
    """
    Met à jour publications.is_validated = TRUE
    pour toute publication ayant au moins un auteur UCA.
    """
    cur.execute("""
        UPDATE publications SET is_validated = TRUE, updated_at = now()
        WHERE id IN (
            SELECT DISTINCT publication_id
            FROM publication_authors
            WHERE is_uca_author = TRUE
        )
        AND is_validated = FALSE
    """)
    return cur.rowcount


def show_stats(cur):
    """Affiche les statistiques de résolution."""
    logger.info("\n--- Statistiques de résolution ---")

    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE affiliation_resolved_at IS NOT NULL) AS resolved,
            COUNT(*) FILTER (WHERE affiliation_resolved_at IS NULL AND raw_affiliation IS NOT NULL) AS pending,
            COUNT(*) FILTER (WHERE raw_affiliation IS NULL) AS no_affiliation,
            COUNT(*) FILTER (WHERE is_uca_author = TRUE AND source = 'openalex') AS uca_openalex,
            COUNT(*) FILTER (WHERE is_uca_author = TRUE AND source = 'hal') AS uca_hal
        FROM publication_authors
    """)
    row = cur.fetchone()
    logger.info(f"  Affiliations résolues   : {row[0]}")
    logger.info(f"  En attente              : {row[1]}")
    logger.info(f"  Sans affiliation brute  : {row[2]}")
    logger.info(f"  Auteurs UCA (OpenAlex)  : {row[3]}")
    logger.info(f"  Auteurs UCA (HAL)       : {row[4]}")

    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE is_validated = TRUE) AS validated,
            COUNT(*) FILTER (WHERE is_validated = FALSE) AS not_validated
        FROM publications
    """)
    row = cur.fetchone()
    logger.info(f"  Publications validées   : {row[0]}")
    logger.info(f"  Non validées            : {row[1]}")

    # Top labos par affiliations résolues (OpenAlex)
    cur.execute("""
        SELECT l.code, l.name, COUNT(*) AS nb
        FROM publication_authors pa
        JOIN laboratories l ON l.id = pa.laboratory_id
        WHERE pa.source = 'openalex'
        GROUP BY l.code, l.name
        ORDER BY nb DESC
        LIMIT 15
    """)
    rows = cur.fetchall()
    if rows:
        logger.info("\n  Top labos (affiliations OpenAlex résolues) :")
        for row in rows:
            logger.info(f"    {row[0]:20s} {row[1]:20s} {row[2]}")


def main():
    parser = argparse.ArgumentParser(description="Résolution des affiliations OpenAlex")
    parser.add_argument("--limit", type=int,
                        help="Nombre max d'affiliations distinctes à traiter")
    parser.add_argument("--reset", action="store_true",
                        help="Remettre toutes les résolutions OpenAlex à zéro")
    parser.add_argument("--stats", action="store_true",
                        help="Afficher les stats sans traiter")
    parser.add_argument("--batch-size", type=int, default=1000,
                        help="Taille du commit batch (défaut: 1000)")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    if args.reset:
        cur.execute("""
            UPDATE publication_authors SET
                is_uca_author = FALSE,
                laboratory_id = NULL,
                affiliation_resolved_at = NULL
            WHERE source = 'openalex'
        """)
        count = cur.rowcount
        cur.execute("UPDATE publications SET is_validated = FALSE")
        # Re-valider les publis qui ont des auteurs HAL déjà résolus
        cur.execute("""
            UPDATE publications SET is_validated = TRUE
            WHERE id IN (
                SELECT DISTINCT publication_id
                FROM publication_authors
                WHERE is_uca_author = TRUE
            )
        """)
        conn.commit()
        logger.info(f"Reset : {count} lignes publication_authors remises à zéro")
        return

    # Charger le validateur
    logger.info("Chargement du validateur de signatures...")
    validator = SignatureValidator(LABOS_JSON, CONFIG_JSON)
    logger.info(f"  {len(validator.labos)} laboratoires chargés")

    # Mapping ROR → lab ID
    ror_to_lab = build_ror_to_lab_id(cur)
    logger.info(f"  {len(ror_to_lab)} laboratoires avec ROR ID en base")

    # Récupérer les affiliations distinctes
    logger.info("Récupération des affiliations distinctes non résolues...")
    affiliations = get_distinct_affiliations(cur, limit=args.limit)
    total = len(affiliations)
    logger.info(f"  {total} affiliations distinctes à traiter")

    if total == 0:
        logger.info("Rien à faire.")
        show_stats(cur)
        conn.close()
        return

    # Résoudre
    processed = 0
    uca_count = 0
    labo_count = 0
    rows_updated = 0
    t_start = time.perf_counter()

    for affiliation in affiliations:
        result = resolve_affiliation(validator, affiliation)

        rows = apply_results(cur, affiliation, result, ror_to_lab)
        rows_updated += rows

        if result["is_uca"]:
            uca_count += 1
        if result["labo_ror"]:
            labo_count += 1

        processed += 1

        if processed % args.batch_size == 0:
            conn.commit()
            elapsed = time.perf_counter() - t_start
            rate = processed / elapsed
            logger.info(
                f"  {processed}/{total} affiliations traitées "
                f"({uca_count} UCA, {labo_count} avec labo) "
                f"— {rate:.0f} affil/s, {rows_updated} lignes MAJ"
            )

    # Commit final
    conn.commit()

    # Mettre à jour is_validated sur les publications
    logger.info("Mise à jour de publications.is_validated...")
    validated = update_publication_validation(cur)
    conn.commit()
    logger.info(f"  {validated} publications marquées comme validées")

    elapsed = time.perf_counter() - t_start
    logger.info(f"\n=== Terminé en {elapsed:.1f}s ===")
    logger.info(f"Affiliations traitées : {processed}")
    logger.info(f"  → UCA : {uca_count} ({100*uca_count/processed:.1f}%)")
    logger.info(f"  → Avec labo : {labo_count} ({100*labo_count/processed:.1f}%)")
    logger.info(f"Lignes publication_authors mises à jour : {rows_updated}")

    # Marquer aussi les affiliations NULL comme résolues (pas UCA par défaut)
    cur.execute("""
        UPDATE publication_authors SET
            affiliation_resolved_at = now()
        WHERE source = 'openalex'
          AND raw_affiliation IS NULL
          AND affiliation_resolved_at IS NULL
    """)
    null_marked = cur.rowcount
    conn.commit()
    if null_marked:
        logger.info(f"  + {null_marked} lignes sans affiliation marquées comme résolues")

    show_stats(cur)
    conn.close()


if __name__ == "__main__":
    main()
