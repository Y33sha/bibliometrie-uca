#!/usr/bin/env python3
"""
Fusionne automatiquement les paires de personnes qui sont à la fois :
- Candidats doublons par nom (même last_name_normalized, first_name compatible)
- En conflit d'auteur sur au moins une publication (même position, sources différentes)

Règles de choix du target :
1. Personne RH prioritaire (JAMAIS fusionner deux personnes RH)
2. Si même patronyme, garder le prénom le plus long
3. Sinon, prompter l'utilisateur

Usage:
    python auto_merge_name_conflict_pairs.py              # exécuter
    python auto_merge_name_conflict_pairs.py --dry-run    # simuler
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.normalize import normalize_name
from services.persons import merge_person


PAIRS_SQL = """
WITH name_candidates AS (
    SELECT p1.id AS id_a, p2.id AS id_b
    FROM persons p1
    JOIN persons p2 ON p1.id < p2.id
      AND p1.last_name_normalized = p2.last_name_normalized
      AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
    WHERE NOT EXISTS (
        SELECT 1 FROM distinct_persons dp
        WHERE dp.person_id_a = LEAST(p1.id, p2.id) AND dp.person_id_b = GREATEST(p1.id, p2.id)
    )
    AND NOT (
        EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p1.id)
        AND EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p2.id)
    )
),
conflict_pairs AS (
    SELECT DISTINCT
        LEAST(oas.person_id, has2.person_id) AS id_a,
        GREATEST(oas.person_id, has2.person_id) AS id_b
    FROM openalex_authorships oas
    JOIN openalex_documents od ON od.id = oas.openalex_document_id
    JOIN hal_documents hd ON hd.publication_id = od.publication_id
    JOIN hal_authorships has2 ON has2.hal_document_id = hd.id
        AND has2.author_position = oas.author_position
    WHERE oas.person_id IS NOT NULL AND has2.person_id IS NOT NULL
      AND oas.person_id <> has2.person_id
    UNION
    SELECT DISTINCT
        LEAST(oas.person_id, was.person_id),
        GREATEST(oas.person_id, was.person_id)
    FROM openalex_authorships oas
    JOIN openalex_documents od ON od.id = oas.openalex_document_id
    JOIN wos_documents wd ON wd.publication_id = od.publication_id
    JOIN wos_authorships was ON was.wos_document_id = wd.id
        AND was.author_position = oas.author_position
    WHERE oas.person_id IS NOT NULL AND was.person_id IS NOT NULL
      AND oas.person_id <> was.person_id
)
SELECT nc.id_a, nc.id_b,
       pa.last_name AS ln_a, pa.first_name AS fn_a,
       pa.last_name_normalized AS lnn_a, pa.first_name_normalized AS fnn_a,
       pb.last_name AS ln_b, pb.first_name AS fn_b,
       pb.last_name_normalized AS lnn_b, pb.first_name_normalized AS fnn_b,
       EXISTS (SELECT 1 FROM persons_rh WHERE person_id = nc.id_a) AS rh_a,
       EXISTS (SELECT 1 FROM persons_rh WHERE person_id = nc.id_b) AS rh_b
FROM name_candidates nc
JOIN conflict_pairs cp ON nc.id_a = cp.id_a AND nc.id_b = cp.id_b
JOIN persons pa ON pa.id = nc.id_a
JOIN persons pb ON pb.id = nc.id_b
ORDER BY nc.id_a, nc.id_b
"""


do_merge = merge_person


def choose_target(pair):
    """Choisit le target (à garder) et le source (à absorber).
    Retourne (target_id, source_id) ou None si prompt nécessaire.
    """
    id_a, id_b = pair["id_a"], pair["id_b"]
    rh_a, rh_b = pair["rh_a"], pair["rh_b"]
    lnn_a, lnn_b = pair["lnn_a"], pair["lnn_b"]
    fnn_a, fnn_b = pair["fnn_a"], pair["fnn_b"]

    # Règle 1 : personne RH prioritaire
    if rh_a and not rh_b:
        return id_a, id_b
    if rh_b and not rh_a:
        return id_b, id_a

    # Règle 2 : même patronyme → prénom le plus long
    if lnn_a == lnn_b:
        if len(fnn_a) >= len(fnn_b):
            return id_a, id_b
        else:
            return id_b, id_a

    # Patronymes différents → prompt
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(PAIRS_SQL)
    pairs = cur.fetchall()
    print(f"{len(pairs)} paires candidats (nom + conflit source)")

    merged = 0
    prompted = 0
    skipped_already_merged = set()

    for pair in pairs:
        # Skip si l'une des personnes a déjà été fusionnée dans ce run
        if pair["id_a"] in skipped_already_merged or pair["id_b"] in skipped_already_merged:
            continue

        choice = choose_target(pair)

        if choice is None:
            # Prompt
            print(f"\n  ? {pair['ln_a']} {pair['fn_a']} (id={pair['id_a']}) vs "
                  f"{pair['ln_b']} {pair['fn_b']} (id={pair['id_b']})")
            resp = input("    Garder [a/b/s(kip)] ? ").strip().lower()
            if resp == "a":
                choice = (pair["id_a"], pair["id_b"])
            elif resp == "b":
                choice = (pair["id_b"], pair["id_a"])
            else:
                prompted += 1
                continue

        target_id, source_id = choice
        if not args.dry_run:
            do_merge(cur, target_id, source_id)
        skipped_already_merged.add(source_id)
        merged += 1

    if args.dry_run:
        conn.rollback()
        print(f"\nDRY-RUN : {merged} fusions simulées, {prompted} à prompter")
    else:
        conn.commit()
        print(f"\n{merged} fusions effectuées, {prompted} skippées (prompt)")

    conn.close()


if __name__ == "__main__":
    main()
