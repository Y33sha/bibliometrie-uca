#!/usr/bin/env python3
"""
enrich_hal_structures.py
========================
Interroge l'API ref/structure de HAL pour enrichir la table source_structures
(source='hal') avec les métadonnées complètes : dates, parents, identifiants
externes, alias, etc.

Les champs spécifiques HAL (type, valid, code, doc_count, parent_ids,
start_date, end_date) sont stockés dans le champ JSONB source_data.
enriched_at est une colonne réelle de source_structures.

Usage:
    python3 enrich_hal_structures.py                # enrichir les structures non-enrichies
    python3 enrich_hal_structures.py --all           # ré-enrichir toutes les structures
    python3 enrich_hal_structures.py --crawl         # + découvrir et enrichir les parents récursivement
    python3 enrich_hal_structures.py --children 1063463  # lister tous les enfants d'une structure
"""

import argparse
import os
import sys
import time
import requests
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
HAL_API = "https://api.archives-ouvertes.fr/ref/structure/"
BATCH_SIZE = 50  # nb de structures par requête API
RATE_LIMIT = 0.3  # secondes entre requêtes

FIELDS = [
    "docid", "name_s", "acronym_s", "type_s", "valid_s",
    "startDate_s", "endDate_s",
    "code_s", "country_s",
    "parentDocid_i",
]


def fetch_batch(struct_ids):
    """Interroge l'API HAL pour un lot de structure IDs."""
    if not struct_ids:
        return []
    
    q = "docid:(" + " OR ".join(str(sid) for sid in struct_ids) + ")"
    params = {
        "q": q,
        "fl": ",".join(FIELDS),
        "rows": len(struct_ids),
        "wt": "json",
    }
    
    resp = requests.get(HAL_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", {}).get("docs", [])


def parse_doc(doc):
    """Extrait les champs d'un document API en dict prêt pour l'insertion.

    Retourne un dict avec :
    - Les colonnes réelles de source_structures (source_id, name, acronym, country, enriched_at)
    - source_data : JSONB contenant type, valid, code, doc_count, parent_ids, start_date, end_date
    """
    def int_list(field):
        """Convertit une liste (parfois de strings) en liste d'ints."""
        val = doc.get(field)
        if not val:
            return None
        return [int(v) for v in val]

    def normalize_date(field):
        """Normalise une date HAL qui peut être 'YYYY', 'YYYY-MM' ou 'YYYY-MM-DD'."""
        val = doc.get(field)
        if not val:
            return None
        val = str(val).strip()
        if len(val) == 4:       # "1869" → "1869-01-01"
            return f"{val}-01-01"
        if len(val) == 7:       # "2021-01" → "2021-01-01"
            return f"{val}-01"
        return val              # "2021-01-01" → tel quel

    # code_s peut contenir des doublons (un par parent), on prend le premier
    codes = doc.get("code_s")
    code = codes[0] if codes else None

    parent_ids = int_list("parentDocid_i")

    return {
        "source_id": str(doc["docid"]),
        "name": doc.get("name_s"),
        "acronym": doc.get("acronym_s"),
        "country": doc.get("country_s"),
        "source_data": {
            "type": doc.get("type_s"),
            "valid": doc.get("valid_s"),
            "start_date": normalize_date("startDate_s"),
            "end_date": normalize_date("endDate_s"),
            "code": code,
            "parent_ids": parent_ids,
        },
    }


def upsert_structures(cur, records):
    """Insère ou met à jour les structures dans source_structures (source='hal')."""
    if not records:
        return 0

    count = 0
    for rec in records:
        source_data_json = psycopg2.extras.Json(rec["source_data"])
        cur.execute("""
            INSERT INTO source_structures (
                source, source_id, name, acronym, country,
                source_data, enriched_at
            ) VALUES (
                'hal', %(source_id)s, COALESCE(%(name)s, '(inconnu)'), %(acronym)s,
                %(country)s, %(source_data)s, now()
            )
            ON CONFLICT (source, source_id) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, '(inconnu)'),
                acronym = EXCLUDED.acronym,
                country = EXCLUDED.country,
                source_data = EXCLUDED.source_data,
                enriched_at = now()
        """, {
            "source_id": rec["source_id"],
            "name": rec["name"],
            "acronym": rec["acronym"],
            "country": rec["country"],
            "source_data": source_data_json,
        })
        count += 1
    return count


def enrich(conn, only_missing=True):
    """Enrichit les structures depuis l'API HAL."""
    cur = conn.cursor()

    if only_missing:
        cur.execute("SELECT source_id::int FROM source_structures WHERE source = 'hal' AND enriched_at IS NULL")
    else:
        cur.execute("SELECT source_id::int FROM source_structures WHERE source = 'hal'")

    ids = [row[0] for row in cur.fetchall()]
    
    if not ids:
        print("Aucune structure à enrichir.")
        return 0
    
    print(f"{len(ids)} structures à enrichir...")
    total = 0
    
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        docs = fetch_batch(batch)
        records = [parse_doc(d) for d in docs]
        count = upsert_structures(cur, records)
        total += count
        
        # Signaler les IDs non trouvés
        found_ids = {d["docid"] for d in docs}
        missing = set(batch) - found_ids
        if missing:
            print(f"  ⚠ IDs non trouvés dans HAL: {missing}")
        
        conn.commit()
        print(f"  Batch {i // BATCH_SIZE + 1}: {count} enrichies ({total}/{len(ids)})")
        
        if i + BATCH_SIZE < len(ids):
            time.sleep(RATE_LIMIT)
    
    print(f"\nTotal: {total} structures enrichies.")
    return total


def crawl_parents(conn):
    """Découvre et enrichit les parents non encore présents dans la table.

    Parcourt récursivement l'arbre des parents jusqu'à ce qu'il n'y ait
    plus de parents inconnus. Permet de reconstruire toute la hiérarchie.
    """
    cur = conn.cursor()
    iteration = 0

    while True:
        iteration += 1

        # Trouver les parent_ids référencés mais pas encore dans la table
        cur.execute("""
            SELECT DISTINCT pid::int
            FROM source_structures ss,
                 LATERAL jsonb_array_elements_text(ss.source_data->'parent_ids') AS pid
            WHERE ss.source = 'hal'
              AND ss.source_data->'parent_ids' IS NOT NULL
            EXCEPT
            SELECT source_id::int FROM source_structures WHERE source = 'hal'
        """)
        missing_parents = [row[0] for row in cur.fetchall()]
        
        if not missing_parents:
            print(f"Crawl terminé après {iteration - 1} itération(s). Arbre complet.")
            break
        
        print(f"\nItération {iteration}: {len(missing_parents)} parents à découvrir...")
        
        total = 0
        for i in range(0, len(missing_parents), BATCH_SIZE):
            batch = missing_parents[i:i + BATCH_SIZE]
            docs = fetch_batch(batch)
            records = [parse_doc(d) for d in docs]
            count = upsert_structures(cur, records)
            total += count
            conn.commit()
            
            if i + BATCH_SIZE < len(missing_parents):
                time.sleep(RATE_LIMIT)
        
        print(f"  → {total} parents insérés et enrichis.")
    
    # Résumé
    cur.execute("SELECT count(*) FROM source_structures WHERE source = 'hal'")
    print(f"\nTotal dans source_structures (hal): {cur.fetchone()[0]} structures.")


def find_children(conn, root_id):
    """Trouve récursivement tous les enfants (directs et indirects) d'une structure.

    Utilise le champ source_data->'parent_ids' : si root_id est dans parent_ids
    d'une structure, c'est un enfant direct. On descend ensuite récursivement.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Charger la structure racine
    cur.execute("""
        SELECT source_id, name, acronym, source_data->>'type' AS type
        FROM source_structures
        WHERE source = 'hal' AND source_id = %s
    """, (str(root_id),))
    root = cur.fetchone()
    if not root:
        print(f"Structure {root_id} non trouvee dans source_structures (hal).")
        return

    print(f"Enfants de: {root['name']} ({root['acronym'] or '?'}) [HAL#{root_id}]\n")

    # Requete recursive
    cur.execute("""
        WITH RECURSIVE children AS (
            -- Enfants directs
            SELECT source_id, name, acronym,
                   source_data->>'type' AS type,
                   source_data->>'valid' AS valid,
                   source_data->>'start_date' AS start_date,
                   source_data->>'end_date' AS end_date,
                   source_data->'parent_ids' AS parent_ids,
                   1 AS depth
            FROM source_structures
            WHERE source = 'hal'
              AND source_data->'parent_ids' @> %s::jsonb

            UNION ALL

            -- Enfants indirects
            SELECT ss.source_id, ss.name, ss.acronym,
                   ss.source_data->>'type' AS type,
                   ss.source_data->>'valid' AS valid,
                   ss.source_data->>'start_date' AS start_date,
                   ss.source_data->>'end_date' AS end_date,
                   ss.source_data->'parent_ids' AS parent_ids,
                   c.depth + 1
            FROM source_structures ss
            JOIN children c ON ss.source_data->'parent_ids' @> to_jsonb(c.source_id::int)
            WHERE ss.source = 'hal'
              AND c.depth < 10  -- securite anti-boucle
        )
        SELECT DISTINCT ON (source_id)
            source_id, name, acronym, type, valid, start_date, end_date, depth
        FROM children
        ORDER BY source_id, depth
    """, (str(root_id),))

    children = cur.fetchall()

    # Grouper par type
    by_type = {}
    for c in children:
        t = c["type"] or "unknown"
        by_type.setdefault(t, []).append(c)

    for typ in sorted(by_type.keys()):
        items = sorted(by_type[typ], key=lambda x: (x["name"] or ""))
        print(f"-- {typ} ({len(items)}) --")
        for c in items:
            status = f" [{c['valid']}]" if c["valid"] else ""
            dates = ""
            if c["start_date"] or c["end_date"]:
                s = str(c["start_date"])[:4] if c["start_date"] else "?"
                e = str(c["end_date"])[:4] if c["end_date"] else "..."
                dates = f" ({s}->{e})"
            acr = f" ({c['acronym']})" if c['acronym'] else ""
            depth_marker = "  " * (c["depth"] - 1) + "|- " if c["depth"] > 1 else ""
            print(f"  {depth_marker}HAL#{c['source_id']:>8}  {c['name']}{acr}{dates}{status}")
        print()

    print(f"Total: {len(children)} structures enfants.")


def main():
    parser = argparse.ArgumentParser(description="Enrichir source_structures (HAL) depuis l'API HAL")
    parser.add_argument("--all", action="store_true",
                        help="Ré-enrichir toutes les structures (pas seulement les manquantes)")
    parser.add_argument("--crawl", action="store_true",
                        help="Découvrir et enrichir récursivement les parents")
    parser.add_argument("--children", type=int, metavar="HAL_ID",
                        help="Lister tous les enfants d'une structure")
    args = parser.parse_args()
    
    conn = get_connection()
    
    try:
        if args.children:
            find_children(conn, args.children)
        else:
            enrich(conn, only_missing=not args.all)
            if args.crawl:
                crawl_parents(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
