#!/usr/bin/env python3
"""
Corrige les openalex_authorships dont le person_id est faux.

Principe : HAL et WoS font autorité pour l'identité des auteurs.
Quand une authorship OA est à la même position qu'un auteur HAL/WoS
et que les person_id divergent, on copie le person_id de HAL/WoS.

Garde anti-décalage : ne corriger que sur les publications où le nombre
d'auteurs est identique entre les sources ET le dernier auteur est le même
(sinon c'est un décalage de positions, pas une fausse entité).

Pass 1 : copier person_id depuis HAL/WoS (publications alignées uniquement)
Pass 2 : fausses entités OA sans HAL/WoS — raw_name ≠ entité, raw_name = nom HAL
"""

import psycopg2
from psycopg2.extras import RealDictCursor

DB = "dbname=publisher_stats user=lalecoz"

# Requête pour identifier les publications alignées entre HAL et OA
ALIGNED_PUBS_CTE = """
aligned_hal_oa AS (
    SELECT hd.publication_id
    FROM hal_documents hd
    JOIN openalex_documents od ON od.publication_id = hd.publication_id
    WHERE EXISTS (
        SELECT 1
        FROM (SELECT COUNT(*) AS c, MAX(author_position) AS mx
              FROM hal_authorships WHERE hal_document_id = hd.id AND NOT excluded) h,
             (SELECT COUNT(*) AS c, MAX(author_position) AS mx
              FROM openalex_authorships WHERE openalex_document_id = od.id AND NOT excluded) o
        WHERE h.c = o.c AND h.mx = o.mx
    )
),
aligned_wos_oa AS (
    SELECT wd.publication_id
    FROM wos_documents wd
    JOIN openalex_documents od ON od.publication_id = wd.publication_id
    WHERE EXISTS (
        SELECT 1
        FROM (SELECT COUNT(*) AS c, MAX(author_position) AS mx
              FROM wos_authorships WHERE wos_document_id = wd.id AND NOT excluded) w,
             (SELECT COUNT(*) AS c, MAX(author_position) AS mx
              FROM openalex_authorships WHERE openalex_document_id = od.id AND NOT excluded) o
        WHERE w.c = o.c AND w.mx = o.mx
    )
)
"""


def main():
    conn = psycopg2.connect(DB)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # ── Pass 1 : copier person_id depuis HAL/WoS sur publications alignées ──
    print("--- Pass 1 : copier person_id depuis HAL/WoS (publications alignées) ---")
    cur.execute(f"""
        WITH {ALIGNED_PUBS_CTE},
        hal_fixes AS (
            SELECT oas.id AS oas_id, oas.person_id AS wrong_pid,
                   ha.person_id AS correct_pid, oas.raw_author_name
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN aligned_hal_oa a ON a.publication_id = od.publication_id
            JOIN hal_documents hd ON hd.publication_id = od.publication_id
            JOIN hal_authorships has2 ON has2.hal_document_id = hd.id
                AND has2.author_position = oas.author_position
            JOIN hal_authors ha ON ha.id = has2.hal_author_id
            WHERE ha.person_id IS NOT NULL
              AND oas.person_id IS DISTINCT FROM ha.person_id
        ),
        wos_fixes AS (
            SELECT oas.id AS oas_id, oas.person_id AS wrong_pid,
                   wa.person_id AS correct_pid, oas.raw_author_name
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN aligned_wos_oa a ON a.publication_id = od.publication_id
            JOIN wos_documents wd ON wd.publication_id = od.publication_id
            JOIN wos_authorships was ON was.wos_document_id = wd.id
                AND was.author_position = oas.author_position
            JOIN wos_authors wa ON wa.id = was.wos_author_id
            WHERE wa.person_id IS NOT NULL
              AND oas.person_id IS DISTINCT FROM wa.person_id
              AND NOT EXISTS (SELECT 1 FROM hal_fixes hf WHERE hf.oas_id = oas.id)
        )
        SELECT f.oas_id, MIN(f.wrong_pid) AS wrong_pid,
               MIN(f.correct_pid) AS correct_pid, MIN(f.raw_author_name) AS raw_author_name
        FROM (
            SELECT oas_id, wrong_pid, correct_pid, raw_author_name FROM hal_fixes
            UNION ALL
            SELECT oas_id, wrong_pid, correct_pid, raw_author_name FROM wos_fixes
        ) f
        GROUP BY f.oas_id
        HAVING COUNT(DISTINCT f.correct_pid) = 1
        ORDER BY f.oas_id
    """)
    raw_fixes = cur.fetchall()
    # Exclure les cas où la correction est contredite par une autre correction du même batch
    # (signe de doublons de personnes côté HAL)
    pid_pairs = set()
    for f in raw_fixes:
        if f['wrong_pid'] is not None:
            pid_pairs.add((f['wrong_pid'], f['correct_pid']))
    conflicting_pids = set()
    for wp, cp in pid_pairs:
        if (cp, wp) in pid_pairs:
            conflicting_pids.add(wp)
            conflicting_pids.add(cp)
    fixes = [f for f in raw_fixes if f['correct_pid'] not in conflicting_pids]
    if len(raw_fixes) != len(fixes):
        print(f"  ({len(raw_fixes) - len(fixes)} corrections exclues — doublons de personnes)")
    print(f"Authorships OA à corriger : {len(fixes)}")

    if fixes:
        for f in fixes[:10]:
            print(f"  OAS {f['oas_id']} : {f['wrong_pid']} → {f['correct_pid']}  "
                  f"(raw: {f['raw_author_name']})")
        if len(fixes) > 10:
            print(f"  ... et {len(fixes) - 10} autres")

        updated = 0
        for f in fixes:
            cur.execute("UPDATE openalex_authorships SET person_id = %s WHERE id = %s",
                        (f['correct_pid'], f['oas_id']))
            updated += cur.rowcount
        print(f"openalex_authorships corrigées : {updated}")

        # Propager aux authorships consolidées (éviter doublons)
        cur.execute("""
            UPDATE authorships a
            SET person_id = oas.person_id
            FROM openalex_authorships oas
            WHERE a.openalex_authorship_id = oas.id
              AND a.person_id IS DISTINCT FROM oas.person_id
              AND oas.person_id IS NOT NULL
              AND oas.id = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1 FROM authorships a2
                  WHERE a2.publication_id = a.publication_id
                    AND a2.person_id = oas.person_id
                    AND a2.id <> a.id
              )
        """, ([f['oas_id'] for f in fixes],))
        print(f"authorships consolidées corrigées : {cur.rowcount}")
    else:
        print("Rien à faire.")

    # ── Pass 2 : marquer les entités OA non fiables ──
    # Entités dont le raw_author_name ne correspond pas au full_name
    cur.execute("""
        UPDATE openalex_authors oa
        SET is_reliable = false
        WHERE oa.is_reliable = true
          AND EXISTS (
              SELECT 1 FROM openalex_authorships oas
              WHERE oas.openalex_author_id = oa.id
                AND oas.raw_author_name IS NOT NULL
                AND unaccent(LOWER(oas.raw_author_name))
                    NOT LIKE '%%' || unaccent(LOWER(COALESCE(oa.last_name, oa.full_name))) || '%%'
                AND unaccent(LOWER(COALESCE(oa.last_name, oa.full_name)))
                    NOT LIKE '%%' || unaccent(LOWER(oas.raw_author_name)) || '%%'
                AND LENGTH(COALESCE(oa.last_name, '')) >= 3
          )
    """)
    newly_unreliable = cur.rowcount
    if newly_unreliable:
        print(f"\n{newly_unreliable} entités OA nouvellement marquées non fiables")

    conn.commit()

    # Nettoyage : personnes orphelines
    cur.execute("""
        WITH orphans AS (
            SELECT p.id FROM persons p
            WHERE NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
              AND NOT EXISTS (SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id)
              AND NOT EXISTS (SELECT 1 FROM wos_authors wa WHERE wa.person_id = p.id)
              AND NOT EXISTS (SELECT 1 FROM persons_rh prh WHERE prh.person_id = p.id)
              AND NOT EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)
        )
        DELETE FROM persons WHERE id IN (SELECT id FROM orphans)
    """)
    orphans = cur.rowcount
    if orphans:
        print(f"{orphans} personnes orphelines supprimées")

    conn.commit()
    conn.close()
    print("Terminé.")


if __name__ == "__main__":
    main()
