"""
Fusionne les personnes homonymes au sein d'un même laboratoire.

Pour chaque labo, détecte les personnes ayant le même nom+prénom normalisé,
affiche les doublons et demande confirmation avant de fusionner.

La personne cible (celle qui absorbe les autres) est celle avec le plus de
publications, ou celle qui a des données RH.

Usage:
    python merge_lab_duplicates.py              # appliquer les fusions confirmées
    python merge_lab_duplicates.py --dry-run    # dry-run interactif
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.merge_persons import merge_person

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

COLORS = {
    "bold": "\033[1m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "red": "\033[31m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def c(text, *styles):
    prefix = "".join(COLORS.get(s, "") for s in styles)
    return f"{prefix}{text}{COLORS['reset']}"


LAB_PERSONS_CTE = """
    WITH lab_persons AS (
        SELECT DISTINCT s.id AS lab_id, s.name AS lab_name, p.id AS person_id,
               p.last_name_normalized, p.first_name_normalized
        FROM structures s
        JOIN (
            SELECT DISTINCT has.structure_ids, ha.person_id
            FROM hal_authorships has
            JOIN hal_authors ha ON ha.id = has.hal_author_id
            WHERE has.is_uca = TRUE AND ha.person_id IS NOT NULL
              AND has.structure_ids IS NOT NULL
        ) h ON s.id = ANY(h.structure_ids)
        JOIN persons p ON p.id = h.person_id
        WHERE s.structure_type = 'labo'
        UNION
        SELECT DISTINCT s.id, s.name, p.id,
               p.last_name_normalized, p.first_name_normalized
        FROM structures s
        JOIN (
            SELECT DISTINCT oas.structure_ids, oa.person_id
            FROM openalex_authorships oas
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
            WHERE oas.is_uca = TRUE AND oa.person_id IS NOT NULL
              AND oas.structure_ids IS NOT NULL
        ) o ON s.id = ANY(o.structure_ids)
        JOIN persons p ON p.id = o.person_id
        WHERE s.structure_type = 'labo'
    )
"""


def get_labs_with_duplicates(cur):
    """Retourne les labos ayant des personnes homonymes."""
    cur.execute(LAB_PERSONS_CTE + """
        SELECT lab_id, lab_name,
               regexp_replace(last_name_normalized, '[-\\s]+', ' ', 'g') AS last_norm,
               regexp_replace(first_name_normalized, '[-\\s]+', ' ', 'g') AS first_norm,
               array_agg(person_id ORDER BY person_id) AS person_ids
        FROM lab_persons
        WHERE last_name_normalized != '' AND first_name_normalized != ''
        GROUP BY lab_id, lab_name, last_norm, first_norm
        HAVING COUNT(*) > 1
        ORDER BY lab_name, last_norm, first_norm
    """)
    return cur.fetchall()


def get_swapped_name_duplicates(cur, lab_id):
    """Retourne les paires (personne A, personne B) dans un labo
    où nom_A = prénom_B et prénom_A = nom_B (interversion nom/prénom)."""
    cur.execute(LAB_PERSONS_CTE + """
        SELECT DISTINCT LEAST(a.person_id, b.person_id) AS id1,
               GREATEST(a.person_id, b.person_id) AS id2
        FROM lab_persons a
        JOIN lab_persons b ON a.lab_id = b.lab_id
            AND a.person_id < b.person_id
            AND regexp_replace(a.last_name_normalized, '[-\\s]+', ' ', 'g')
              = regexp_replace(b.first_name_normalized, '[-\\s]+', ' ', 'g')
            AND regexp_replace(a.first_name_normalized, '[-\\s]+', ' ', 'g')
              = regexp_replace(b.last_name_normalized, '[-\\s]+', ' ', 'g')
        WHERE a.lab_id = %s
          AND a.last_name_normalized != '' AND a.first_name_normalized != ''
          AND b.last_name_normalized != '' AND b.first_name_normalized != ''
    """, (lab_id,))
    return cur.fetchall()


def get_labs_with_swaps(cur):
    """Retourne les labos ayant des interversions nom/prénom."""
    cur.execute(LAB_PERSONS_CTE + """
        SELECT DISTINCT a.lab_id, s.name AS lab_name
        FROM lab_persons a
        JOIN lab_persons b ON a.lab_id = b.lab_id
            AND a.person_id < b.person_id
            AND regexp_replace(a.last_name_normalized, '[-\\s]+', ' ', 'g')
              = regexp_replace(b.first_name_normalized, '[-\\s]+', ' ', 'g')
            AND regexp_replace(a.first_name_normalized, '[-\\s]+', ' ', 'g')
              = regexp_replace(b.last_name_normalized, '[-\\s]+', ' ', 'g')
        JOIN structures s ON s.id = a.lab_id
        WHERE a.last_name_normalized != '' AND a.first_name_normalized != ''
          AND b.last_name_normalized != '' AND b.first_name_normalized != ''
    """)
    return {row["lab_id"]: row["lab_name"] for row in cur.fetchall()}


def get_person_details(cur, person_ids):
    """Récupère les détails des personnes pour affichage."""
    cur.execute("""
        SELECT p.id, p.last_name, p.first_name,
               prh.department_name, prh.role_title,
               (prh.id IS NOT NULL) AS has_rh,
               (SELECT COUNT(DISTINCT pub_id) FROM (
                    SELECT hd.publication_id AS pub_id
                    FROM hal_authors ha2
                    JOIN hal_authorships has2 ON has2.hal_author_id = ha2.id
                    JOIN hal_documents hd ON hd.id = has2.hal_document_id
                    WHERE ha2.person_id = p.id AND hd.publication_id IS NOT NULL
                    UNION
                    SELECT od.publication_id
                    FROM openalex_authors oa2
                    JOIN openalex_authorships oas2 ON oas2.openalex_author_id = oa2.id
                    JOIN openalex_documents od ON od.id = oas2.openalex_document_id
                    WHERE oa2.person_id = p.id AND od.publication_id IS NOT NULL
                ) _pubs) AS pub_count,
               (SELECT array_agg(DISTINCT pi.id_type || ':' || pi.id_value)
                FROM person_identifiers pi
                WHERE pi.person_id = p.id AND pi.status != 'rejected') AS identifiers,
               (SELECT COUNT(*) FROM hal_authors ha WHERE ha.person_id = p.id) AS hal_authors,
               (SELECT COUNT(*) FROM openalex_authors oa WHERE oa.person_id = p.id) AS oa_authors
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = ANY(%s)
        ORDER BY
            (prh.id IS NOT NULL) DESC,
            (SELECT COUNT(DISTINCT pub_id) FROM (
                SELECT hd.publication_id AS pub_id
                FROM hal_authors ha2
                JOIN hal_authorships has2 ON has2.hal_author_id = ha2.id
                JOIN hal_documents hd ON hd.id = has2.hal_document_id
                WHERE ha2.person_id = p.id AND hd.publication_id IS NOT NULL
                UNION
                SELECT od.publication_id
                FROM openalex_authors oa2
                JOIN openalex_authorships oas2 ON oas2.openalex_author_id = oa2.id
                JOIN openalex_documents od ON od.id = oas2.openalex_document_id
                WHERE oa2.person_id = p.id AND od.publication_id IS NOT NULL
            ) _pubs) DESC,
            p.id ASC
    """, (person_ids,))
    return cur.fetchall()


def pick_target(persons):
    """Choisit la personne cible : RH d'abord, puis max publications."""
    # Le tri SQL met déjà la meilleure en premier
    return persons[0]


do_merge = merge_person


def display_person(p, is_target=False):
    """Affiche une ligne pour une personne."""
    marker = c(" ← CIBLE", "green", "bold") if is_target else ""
    rh = c(" [RH]", "cyan") if p["has_rh"] else ""
    ids = ""
    if p["identifiers"]:
        ids = " " + " ".join(c(i, "dim") for i in p["identifiers"])
    dept = f" ({p['department_name']})" if p["department_name"] else ""
    role = f" [{p['role_title']}]" if p["role_title"] else ""

    print(f"    #{p['id']:>5d}  {p['last_name']} {p['first_name']}"
          f"{rh}{dept}{role}"
          f"  — {p['pub_count']} publis, {p['hal_authors']} HAL, {p['oa_authors']} OA"
          f"{ids}{marker}")


def run(dry_run=False):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    rows = get_labs_with_duplicates(cur)

    # Grouper par labo (passe 1 : homonymes)
    labs = {}
    for row in rows:
        lab_id = row["lab_id"]
        if lab_id not in labs:
            labs[lab_id] = {"name": row["lab_name"], "groups": []}
        labs[lab_id]["groups"].append(row["person_ids"])

    # Ajouter les labos qui n'ont que des interversions (passe 2)
    swap_labs = get_labs_with_swaps(cur)
    for lab_id, lab_name in swap_labs.items():
        if lab_id not in labs:
            labs[lab_id] = {"name": lab_name, "groups": []}

    logger.info(f"{len(labs)} laboratoires avec des doublons potentiels")
    logger.info(f"{len(rows)} groupes de personnes homonymes\n")

    total_merged = 0
    total_skipped = 0

    for lab_id, lab_data in sorted(labs.items(), key=lambda x: x[1]["name"]):
        groups = lab_data["groups"]

        # Dédupliquer les groupes (une même paire peut apparaître dans plusieurs labos)
        # On garde tous les groupes pour ce labo

        print(f"\n{'='*70}")
        print(c(f"  {lab_data['name']}", "bold") + c(f"  (id={lab_id})", "dim"))
        if groups:
            print(f"  {len(groups)} groupe(s) d'homonymes")
        print(f"{'='*70}")

        # Afficher tous les groupes de ce labo
        merge_plan = []  # list of (target, sources)

        for i, person_ids in enumerate(groups):
            persons = get_person_details(cur, person_ids)
            if len(persons) < 2:
                continue  # déjà fusionnés entre-temps

            # Vérifier si plusieurs personnes ont une fiche RH distincte → fusion interdite
            rh_persons = [p for p in persons if p["has_rh"]]
            if len(rh_persons) >= 2:
                print(c(f"\n  ⛔ Groupe {i+1}: {len(rh_persons)} personnes avec fiche RH — fusion interdite", "red"))
                for p in persons:
                    display_person(p)
                print(c("    → Ignoré (fiches RH distinctes).", "dim"))
                total_skipped += 1
                continue

            # Vérifier les conflits d'ORCID
            orcids = set()
            for p in persons:
                if p["identifiers"]:
                    for ident in p["identifiers"]:
                        if ident.startswith("orcid:"):
                            orcids.add(ident.split(":", 1)[1])
            has_orcid_conflict = len(orcids) > 1

            target = pick_target(persons)
            sources = [p for p in persons if p["id"] != target["id"]]

            if has_orcid_conflict:
                print(c(f"\n  ⚠ Groupe {i+1}: ORCIDs différents ({', '.join(orcids)})", "red"))
            else:
                print(f"\n  Groupe {i+1}:")
            display_person(target, is_target=True)
            for s in sources:
                display_person(s)

            if has_orcid_conflict:
                try:
                    ans = input(c("    Fusionner malgré les ORCIDs différents ? [o]ui / [N]on : ", "yellow")).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nInterrompu.")
                    return
                if ans not in ("o", "oui", "y", "yes"):
                    total_skipped += 1
                    print(c("    → Ignoré.", "dim"))
                    continue

            merge_plan.append((target, sources))

        if not merge_plan:
            print(c("  Aucune fusion d'homonymes pour ce labo.", "dim"))
        else:
            # Demander confirmation passe 1
            print()
            try:
                answer = input(c(f"  Fusionner ces {len(merge_plan)} groupe(s) d'homonymes ? [O]ui / [n]on / [q]uitter : ", "yellow")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nInterrompu.")
                break

            if answer == "q":
                print("Arrêt demandé.")
                break
            elif answer in ("n", "non"):
                total_skipped += len(merge_plan)
                print(c("  → Ignoré.", "dim"))
            else:
                for target, sources in merge_plan:
                    for source in sources:
                        if not dry_run:
                            do_merge(cur, target["id"], source["id"])
                            logger.info(f"  Fusionné #{source['id']} → #{target['id']} "
                                        f"({source['last_name']} {source['first_name']})")
                        else:
                            logger.info(f"  [dry-run] Fusionnerait #{source['id']} → #{target['id']} "
                                        f"({source['last_name']} {source['first_name']})")
                        total_merged += 1
                if not dry_run:
                    conn.commit()

        # ── Passe 2 : interversions nom/prénom ──
        swapped = get_swapped_name_duplicates(cur, lab_id)
        if swapped:
            swap_plan = []
            print(c(f"\n  --- Passe 2 : interversions nom/prénom ({len(swapped)} paire(s)) ---", "bold"))

            for row in swapped:
                pair_ids = [row["id1"], row["id2"]]
                persons = get_person_details(cur, pair_ids)
                if len(persons) < 2:
                    continue

                # Vérifier si les deux personnes ont une fiche RH → fusion interdite
                rh_persons = [p for p in persons if p["has_rh"]]
                if len(rh_persons) >= 2:
                    print(c(f"\n  ⛔ Interversion — {len(rh_persons)} personnes avec fiche RH — fusion interdite", "red"))
                    for p in persons:
                        display_person(p)
                    print(c("    → Ignoré (fiches RH distinctes).", "dim"))
                    total_skipped += 1
                    continue

                # Vérifier conflit ORCID
                orcids = set()
                for p in persons:
                    if p["identifiers"]:
                        for ident in p["identifiers"]:
                            if ident.startswith("orcid:"):
                                orcids.add(ident.split(":", 1)[1])
                has_orcid_conflict = len(orcids) > 1

                target = pick_target(persons)
                sources = [p for p in persons if p["id"] != target["id"]]

                if has_orcid_conflict:
                    print(c(f"\n  ⚠ Interversion — ORCIDs différents ({', '.join(orcids)})", "red"))
                else:
                    print(f"\n  Interversion :")
                display_person(target, is_target=True)
                for s in sources:
                    display_person(s)

                if has_orcid_conflict:
                    try:
                        ans = input(c("    Fusionner malgré les ORCIDs différents ? [o]ui / [N]on : ", "yellow")).strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print("\nInterrompu.")
                        return
                    if ans not in ("o", "oui", "y", "yes"):
                        total_skipped += 1
                        print(c("    → Ignoré.", "dim"))
                        continue

                swap_plan.append((target, sources))

            if swap_plan:
                print()
                try:
                    answer = input(c(f"  Fusionner ces {len(swap_plan)} interversion(s) ? [O]ui / [n]on / [q]uitter : ", "yellow")).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nInterrompu.")
                    break

                if answer == "q":
                    print("Arrêt demandé.")
                    break
                elif answer in ("n", "non"):
                    total_skipped += len(swap_plan)
                    print(c("  → Ignoré.", "dim"))
                else:
                    for target, sources in swap_plan:
                        for source in sources:
                            if not dry_run:
                                do_merge(cur, target["id"], source["id"])
                                logger.info(f"  Fusionné (interversion) #{source['id']} → #{target['id']} "
                                            f"({source['last_name']} {source['first_name']})")
                            else:
                                logger.info(f"  [dry-run] Fusionnerait (interversion) #{source['id']} → #{target['id']} "
                                            f"({source['last_name']} {source['first_name']})")
                            total_merged += 1
                    if not dry_run:
                        conn.commit()

    # Résumé
    print(f"\n{'='*70}")
    print(c("  RÉSUMÉ", "bold"))
    print(f"  Fusions effectuées : {total_merged}")
    print(f"  Groupes ignorés   : {total_skipped}")
    if dry_run and total_merged > 0:
        print(c("  (dry-run — aucune modification effectuée)", "yellow"))
    print(f"{'='*70}\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fusionner les personnes homonymes par labo")
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
