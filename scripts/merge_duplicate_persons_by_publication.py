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

from psycopg2.extras import RealDictCursor

from db.connection import get_connection
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
        LEAST(sa1.person_id, sa2.person_id) AS id_a,
        GREATEST(sa1.person_id, sa2.person_id) AS id_b
    FROM source_authorships sa1
    JOIN source_publications sd1 ON sd1.id = sa1.source_publication_id
    JOIN source_publications sd2 ON sd2.publication_id = sd1.publication_id
        AND sd2.source != sd1.source
    JOIN source_authorships sa2 ON sa2.source_publication_id = sd2.id
        AND sa2.author_position = sa1.author_position
    WHERE sa1.person_id IS NOT NULL AND sa2.person_id IS NOT NULL
      AND sa1.person_id <> sa2.person_id
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
