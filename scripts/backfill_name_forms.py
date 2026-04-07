"""
Peuple publisher_name_forms et journal_name_forms depuis les entités existantes,
puis fusionne les doublons exacts (même name_normalized → même forme de nom).

Usage:
    python scripts/backfill_name_forms.py              # dry-run
    python scripts/backfill_name_forms.py --apply       # appliquer
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.log import setup_logger

logger = setup_logger("backfill_name_forms", "processing/logs")


def backfill_forms(cur, conn, apply: bool):
    """Insère une forme de nom par entité existante (si pas déjà présente)."""
    # Publishers
    cur.execute("""
        INSERT INTO publisher_name_forms (publisher_id, form_normalized)
        SELECT id, name_normalized FROM publishers
        ON CONFLICT (form_normalized) DO NOTHING
    """)
    pub_forms = cur.rowcount
    print(f"Publisher name forms insérées : {pub_forms}")

    # Journals (avec publisher_id)
    cur.execute("""
        INSERT INTO journal_name_forms (journal_id, form_normalized, publisher_id)
        SELECT id, title_normalized, publisher_id FROM journals
        ON CONFLICT (form_normalized, publisher_id) DO NOTHING
    """)
    jnl_forms = cur.rowcount
    print(f"Journal name forms insérées : {jnl_forms}")

    if apply:
        conn.commit()

    return pub_forms, jnl_forms


def find_duplicate_publishers(cur):
    """Trouve les publishers ayant le même name_normalized (doublons exacts)."""
    cur.execute("""
        SELECT name_normalized, array_agg(id ORDER BY id) AS ids
        FROM publishers
        GROUP BY name_normalized
        HAVING count(*) > 1
    """)
    return [(r["name_normalized"], r["ids"]) for r in cur.fetchall()]


def find_duplicate_journals(cur):
    """Trouve les journals ayant le même title_normalized."""
    cur.execute("""
        SELECT title_normalized, array_agg(id ORDER BY id) AS ids
        FROM journals
        GROUP BY title_normalized
        HAVING count(*) > 1
    """)
    return [(r["title_normalized"], r["ids"]) for r in cur.fetchall()]


def merge_publishers(cur, target_id: int, source_id: int):
    """Fusionne un publisher source dans un publisher cible."""
    # Transférer les journaux
    cur.execute("UPDATE journals SET publisher_id = %s WHERE publisher_id = %s",
                (target_id, source_id))
    # Transférer les apc_payments
    cur.execute("""
        UPDATE apc_payments SET publisher_id = %s
        WHERE publisher_id = %s
    """, (target_id, source_id))
    # Récupérer l'openalex_id de la source avant de le supprimer
    cur.execute("SELECT openalex_id FROM publishers WHERE id = %s", (source_id,))
    source_oaid = cur.fetchone()["openalex_id"]
    # Supprimer l'openalex_id de la source pour éviter le conflit unique
    cur.execute("UPDATE publishers SET openalex_id = NULL WHERE id = %s", (source_id,))
    # Enrichir la cible avec openalex_id (seulement si la cible n'en a pas)
    if source_oaid:
        cur.execute("""
            UPDATE publishers SET openalex_id = %s
            WHERE id = %s AND openalex_id IS NULL
        """, (source_oaid, target_id))
    # Transférer les name forms (supprimer les doublons d'abord)
    cur.execute("""
        DELETE FROM publisher_name_forms
        WHERE publisher_id = %s AND form_normalized IN (
            SELECT form_normalized FROM publisher_name_forms WHERE publisher_id = %s
        )
    """, (source_id, target_id))
    cur.execute("""
        UPDATE publisher_name_forms SET publisher_id = %s
        WHERE publisher_id = %s
    """, (target_id, source_id))
    # Transférer les journal_name_forms qui référencent ce publisher
    # Supprimer celles qui créeraient un conflit unique
    cur.execute("""
        DELETE FROM journal_name_forms
        WHERE publisher_id = %s
          AND (form_normalized, %s::integer) IN (
              SELECT form_normalized, publisher_id
              FROM journal_name_forms WHERE publisher_id = %s
          )
    """, (source_id, target_id, target_id))
    cur.execute("""
        UPDATE journal_name_forms SET publisher_id = %s
        WHERE publisher_id = %s
    """, (target_id, source_id))
    # Supprimer la source
    cur.execute("DELETE FROM publishers WHERE id = %s", (source_id,))


def merge_journals(cur, target_id: int, source_id: int):
    """Fusionne un journal source dans un journal cible."""
    # Transférer les publications
    cur.execute("UPDATE publications SET journal_id = %s WHERE journal_id = %s",
                (target_id, source_id))
    # Transférer les apc_payments
    cur.execute("""
        UPDATE apc_payments SET journal_id = %s
        WHERE journal_id = %s
    """, (target_id, source_id))
    # Récupérer les métadonnées de la source avant de supprimer son openalex_id
    cur.execute("SELECT openalex_id FROM journals WHERE id = %s", (source_id,))
    source_oaid = cur.fetchone()["openalex_id"]
    # Supprimer l'openalex_id de la source pour éviter le conflit unique
    cur.execute("UPDATE journals SET openalex_id = NULL WHERE id = %s", (source_id,))
    # Enrichir la cible
    cur.execute("""
        UPDATE journals dest SET
            issn = COALESCE(dest.issn, src.issn),
            eissn = COALESCE(dest.eissn, src.eissn),
            issnl = COALESCE(dest.issnl, src.issnl),
            publisher_id = COALESCE(dest.publisher_id, src.publisher_id),
            oa_model = COALESCE(dest.oa_model, src.oa_model)
        FROM journals src
        WHERE dest.id = %s AND src.id = %s
    """, (target_id, source_id))
    if source_oaid:
        cur.execute("""
            UPDATE journals SET openalex_id = %s
            WHERE id = %s AND openalex_id IS NULL
        """, (source_oaid, target_id))
    # Transférer les name forms (supprimer celles qui créeraient un conflit)
    cur.execute("""
        DELETE FROM journal_name_forms
        WHERE journal_id = %s AND (form_normalized, publisher_id) IN (
            SELECT form_normalized, publisher_id
            FROM journal_name_forms WHERE journal_id = %s
        )
    """, (source_id, target_id))
    cur.execute("""
        UPDATE journal_name_forms SET journal_id = %s
        WHERE journal_id = %s
    """, (target_id, source_id))
    # Supprimer la source
    cur.execute("DELETE FROM journals WHERE id = %s", (source_id,))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Peupler les name_forms
    print("=== Peuplement des name_forms ===")
    backfill_forms(cur, conn, apply=args.apply)

    # 2. Fusionner les doublons publishers
    dup_pubs = find_duplicate_publishers(cur)
    print(f"\n=== Publishers : {len(dup_pubs)} groupes de doublons ===")
    pub_merged = 0
    for name_norm, ids in dup_pubs:
        target = ids[0]
        for source in ids[1:]:
            print(f"  {'MERGE' if args.apply else 'DRY'} publisher {source} → {target} ({name_norm})")
            if args.apply:
                merge_publishers(cur, target, source)
            pub_merged += 1

    # 3. Fusionner les doublons journals (seulement ceux sans ISSN discriminant)
    dup_jnls = find_duplicate_journals(cur)
    jnl_merged = 0
    jnl_skipped = 0
    safe_merges = []

    for title_norm, ids in dup_jnls:
        # Récupérer les ISSN de chaque journal du groupe
        cur.execute("""
            SELECT id, issn, eissn, issnl, openalex_id FROM journals WHERE id = ANY(%s) ORDER BY id
        """, (list(ids),))
        rows = cur.fetchall()

        # Fusionner si :
        # - ISSN identiques (doublon exact), ou
        # - ISSN de l'un = eISSN/ISSNL de l'autre (print vs electronic)
        all_issns = set()
        all_eissns = set()
        all_issnls = set()
        for r in rows:
            if r["issn"]: all_issns.add(r["issn"])
            if r["eissn"]: all_eissns.add(r["eissn"])
            if r["issnl"]: all_issnls.add(r["issnl"])

        # Vérifier qu'il y a un recouvrement entre les ISSN des différentes entrées
        all_identifiers = all_issns | all_eissns | all_issnls
        has_cross_match = bool(
            (all_issns & all_eissns) or   # issn de l'un = eissn de l'autre
            (all_issns & all_issnls) or    # issn de l'un = issnl de l'autre
            (all_eissns & all_issnls) or   # eissn de l'un = issnl de l'autre
            len(all_issns) <= 1            # même issn ou un seul renseigné
        )

        if not has_cross_match and len(all_issns) > 1:
            jnl_skipped += 1
            continue

        safe_merges.append((title_norm, ids))

    print(f"\n=== Journals : {len(safe_merges)} groupes fusionnables "
          f"({jnl_skipped} ignorés car ISSN divergents) ===")

    for title_norm, ids in safe_merges:
        target = ids[0]
        for source in ids[1:]:
            print(f"  {'MERGE' if args.apply else 'DRY'} journal {source} → {target} ({title_norm[:50]})")
            if args.apply:
                merge_journals(cur, target, source)
            jnl_merged += 1

    if args.apply:
        conn.commit()

    print(f"\nRésumé :")
    print(f"  Publishers fusionnés : {pub_merged}")
    print(f"  Journals fusionnés : {jnl_merged}")
    print(f"  Journals ignorés (ISSN divergents) : {jnl_skipped}")
    if not args.apply and (pub_merged or jnl_merged):
        print("\nDry-run — ajouter --apply pour appliquer.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
