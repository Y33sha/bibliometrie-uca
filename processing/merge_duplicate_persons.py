"""
Fusionne les personnes en doublon : même nom normalisé + même position
sur la même publication.

Détecte les paires (person_a, person_b) qui co-apparaissent sur une même
publication avec la même author_position et le même nom normalisé.
Fusionne person_b dans person_a (transfère auteurs, authorships,
identifiants, puis supprime person_b).

Usage:
    python merge_duplicate_persons.py              # exécuter
    python merge_duplicate_persons.py --dry-run    # dry-run
"""

import argparse
import logging
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "merge_duplicate_persons.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


def normalize_name(name):
    if not name:
        return ""
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015]", "-", name)
    text = unicodedata.normalize("NFKD", text.lower().strip())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z\s-]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def name_tokens(last, first):
    """Retourne l'ensemble trié des tokens normalisés (nom + prénom mélangés)."""
    full = f"{normalize_name(last)} {normalize_name(first)}"
    return tuple(sorted(full.split()))


def find_duplicates(cur):
    """Trouve les paires de personnes à fusionner.

    Critère : même publication, même author_position, mêmes tokens de nom
    (insensible à la répartition nom/prénom).
    """
    cur.execute("""
        SELECT a1.person_id AS pid1, a2.person_id AS pid2,
               p1.last_name AS ln1, p1.first_name AS fn1,
               p2.last_name AS ln2, p2.first_name AS fn2,
               a1.publication_id, a1.author_position
        FROM authorships a1
        JOIN authorships a2 ON a1.publication_id = a2.publication_id
                           AND a1.author_position = a2.author_position
                           AND a1.person_id < a2.person_id
        JOIN persons p1 ON p1.id = a1.person_id
        JOIN persons p2 ON p2.id = a2.person_id
        LEFT JOIN persons_rh prh1 ON prh1.person_id = p1.id
        LEFT JOIN persons_rh prh2 ON prh2.person_id = p2.id
        WHERE a1.author_position IS NOT NULL
          AND NOT a1.excluded AND NOT a2.excluded
          -- JAMAIS fusionner deux personnes ayant chacune une fiche RH distincte
          AND NOT (prh1.id IS NOT NULL AND prh2.id IS NOT NULL)
    """)

    pairs = {}  # (target, source) -> info
    for row in cur.fetchall():
        tokens1 = name_tokens(row["ln1"], row["fn1"])
        tokens2 = name_tokens(row["ln2"], row["fn2"])

        if not tokens1 or not tokens2:
            continue

        # Match exact sur tous les tokens, OU l'un est un sous-ensemble de l'autre
        # (gère "Jabaudon" vs "Jabaudon Gandet" → tokens2 ⊃ tokens1)
        set1, set2 = set(tokens1), set(tokens2)
        if set1 == set2 or (set1 and set2 and (set1 <= set2 or set2 <= set1)):
            target = min(row["pid1"], row["pid2"])
            source = max(row["pid1"], row["pid2"])
            if (target, source) not in pairs:
                pairs[(target, source)] = {
                    "target_name": f"{row['fn1']} {row['ln1']}",
                    "source_name": f"{row['fn2']} {row['ln2']}",
                    "pub_id": row["publication_id"],
                    "position": row["author_position"],
                }

    return pairs


def resolve_target(merged_into, pid):
    """Suit la chaîne de fusions pour trouver la cible finale."""
    visited = set()
    while pid in merged_into:
        if pid in visited:
            break
        visited.add(pid)
        pid = merged_into[pid]
    return pid


def merge_person(cur, target_id, source_id):
    """Fusionne source dans target (même logique que l'API /merge)."""

    # Garde-fou : ne JAMAIS fusionner si les deux ont une fiche RH
    cur.execute("""
        SELECT COUNT(*) AS n FROM persons_rh
        WHERE person_id IN (%s, %s)
    """, (target_id, source_id))
    if cur.fetchone()["n"] >= 2:
        raise RuntimeError(
            f"REFUS de fusion : les personnes #{target_id} et #{source_id} "
            f"ont chacune une fiche RH distincte."
        )

    # 1. Transférer les auteurs HAL
    cur.execute("UPDATE hal_authors SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 2. Transférer les authorships OpenAlex
    cur.execute("UPDATE openalex_authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 3. Transférer les auteurs WoS
    cur.execute("UPDATE wos_authors SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 4. Transférer les authorships (supprimer les doublons publication)
    cur.execute("""
        DELETE FROM authorships
        WHERE person_id = %s
          AND publication_id IN (
              SELECT publication_id FROM authorships WHERE person_id = %s
          )
    """, (source_id, target_id))
    cur.execute("UPDATE authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 5. Transférer les identifiants (supprimer doublons)
    cur.execute("""
        DELETE FROM person_identifiers
        WHERE person_id = %s
          AND (id_type, id_value) IN (
              SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
          )
    """, (source_id, target_id))
    cur.execute("UPDATE person_identifiers SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 6. Transférer persons_rh de la source vers la cible (si la cible n'en a pas)
    cur.execute("""
        UPDATE persons_rh SET person_id = %s
        WHERE person_id = %s
          AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
    """, (target_id, source_id, target_id))

    # 7. Supprimer la personne source
    cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)

        pairs = find_duplicates(cur)
        logger.info(f"{len(pairs)} paires de personnes à fusionner")

        if not pairs:
            logger.info("Rien à faire.")
            return

        # Résoudre les chaînes (si A→B et B→C, alors A→C)
        merged_into = {}
        merges = []

        for (target, source), info in sorted(pairs.items()):
            final_target = resolve_target(merged_into, target)
            if final_target == source:
                continue  # boucle, skip
            merged_into[source] = final_target
            merges.append((final_target, source, info))

        logger.info(f"{len(merges)} fusions effectives (après résolution des chaînes)")

        for target_id, source_id, info in merges:
            logger.info(
                f"  Fusion : {info['source_name']} (#{source_id}) "
                f"→ {info['target_name']} (#{target_id}) "
                f"[pub {info['pub_id']}, pos {info['position']}]"
            )
            if not args.dry_run:
                merge_person(cur, target_id, source_id)

        if not args.dry_run:
            # Stats après fusion
            cur.execute("SELECT COUNT(*) AS n FROM persons")
            total_persons = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM authorships")
            total_authorships = cur.fetchone()["n"]
            cur.execute("""
                SELECT COUNT(*) AS n FROM authorships a1
                JOIN authorships a2 ON a1.publication_id = a2.publication_id
                                   AND a1.author_position = a2.author_position
                                   AND a1.person_id < a2.person_id
                JOIN persons p1 ON p1.id = a1.person_id
                JOIN persons p2 ON p2.id = a2.person_id
                WHERE a1.author_position IS NOT NULL
                  AND NOT a1.excluded AND NOT a2.excluded
                  AND p1.last_name_normalized = p2.last_name_normalized
                  AND p1.first_name_normalized = p2.first_name_normalized
                  AND p1.last_name_normalized != ''
                  AND p1.first_name_normalized != ''
            """)
            remaining = cur.fetchone()["n"]

            conn.commit()
            logger.info(f"\n=== Résultat ===")
            logger.info(f"  Personnes fusionnées  : {len(merges)}")
            logger.info(f"  Personnes restantes   : {total_persons}")
            logger.info(f"  Authorships restants  : {total_authorships}")
            logger.info(f"  Doublons résiduels    : {remaining}")
        else:
            conn.rollback()
            logger.info(f"\n=== DRY-RUN ===")
            logger.info(f"  Paires détectées      : {len(pairs)}")
            logger.info(f"  Fusions effectives    : {len(merges)}")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
