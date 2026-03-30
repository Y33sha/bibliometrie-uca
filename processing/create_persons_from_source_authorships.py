"""
Crée des entités Personnes à partir des authorships sources UCA non rattachées.

Algorithme source-agnostique en 6 passes :

  Passe 0 : Comptes HAL (hal_authors avec hal_person_id) → création/matching personne
  Passe 1 : Lookup person_name_forms (toutes sources)
  Passe 2 : Nom + co-publication vers personnes existantes
  Passe 3 : Nom seul (candidat unique)
  Passe 4 : Groupement orphelins par nom + co-publication (union-find) → création
             Avant chaque création : vérification nom compatible + co-publication
  Passe 5 : Singletons restants → création (avec même vérification)

La propagation is_uca/structure_ids vers les authorships (table de vérité) est
assurée par build_authorships.py (étape 4), pas par ce script.

Usage:
    python create_persons_from_source_authorships.py              # exécuter
    python create_persons_from_source_authorships.py --dry-run    # dry-run
"""

import argparse
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.normalize import normalize_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_raw_author_name(raw_name):
    """Parse un raw_author_name en (last_name, first_name)."""
    if not raw_name:
        return "", ""
    raw = raw_name.strip()
    if "," in raw:
        parts = raw.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    words = raw.split()
    if len(words) >= 2:
        return words[-1], " ".join(words[:-1])
    return raw, ""


def first_names_compatible(fn1, fn2):
    """Vérifie si deux prénoms normalisés sont compatibles.
    Compatible = identique, initiale de l'autre, ou préfixe (Jean vs Jean-Luc).
    """
    if not fn1 or not fn2:
        return False
    if fn1[0] != fn2[0]:
        return False
    if fn1 == fn2:
        return True
    # Initiale
    if len(fn1) == 1 or len(fn2) == 1:
        return True
    # Préfixe (avec espace: "jean" vs "jean luc")
    fn1s = fn1.replace("-", " ")
    fn2s = fn2.replace("-", " ")
    if fn1s.startswith(fn2s + " ") or fn2s.startswith(fn1s + " "):
        return True
    return False


def last_names_compatible(ln1, ln2):
    """Vérifie si deux noms de famille normalisés sont compatibles.
    Compatible = identique, ou l'un est préfixe de l'autre (composé vs simple).
    """
    if not ln1 or not ln2:
        return False
    if ln1 == ln2:
        return True
    ln1s = ln1.replace("-", " ")
    ln2s = ln2.replace("-", " ")
    if ln1s == ln2s:
        return True
    if ln2s.startswith(ln1s + " ") or ln1s.startswith(ln2s + " "):
        return True
    return False


def names_compatible(ln1, fn1, ln2, fn2):
    """Vérifie si deux paires (nom, prénom) normalisées sont compatibles."""
    # Ordre normal
    if last_names_compatible(ln1, ln2) and first_names_compatible(fn1, fn2):
        return True
    # Inversion nom/prénom
    if last_names_compatible(ln1, fn2) and first_names_compatible(fn1, ln2):
        return True
    return False


def pick_best_name(authorships):
    """Choisit le meilleur nom parmi un groupe (celui avec le plus de publis)."""
    best = max(authorships, key=lambda a: len(a.get("pub_ids", [])))
    return best["last_name"] or "", best["first_name"] or ""


def create_person(cur, last_name, first_name):
    """Crée une personne et retourne son id."""
    last_norm = normalize_name(last_name)
    first_norm = normalize_name(first_name)
    cur.execute("""
        INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, (last_name, first_name, last_norm, first_norm))
    return cur.fetchone()["id"]


def link_to_person(cur, person_id, authorships):
    """Rattache des authorships à une personne (écrit sur les tables sources)."""
    for a in authorships:
        src = a["source"]
        if src == "hal":
            cur.execute("UPDATE hal_authorships SET person_id = %s WHERE id = %s",
                        (person_id, a["authorship_id"]))
            # Dual-write pour les comptes HAL
            if a.get("hal_author_id") and a.get("has_hal_person_id"):
                cur.execute("""UPDATE hal_authors SET person_id = %s, updated_at = now()
                               WHERE id = %s AND hal_person_id IS NOT NULL""",
                            (person_id, a["hal_author_id"]))
        elif src == "openalex":
            cur.execute("UPDATE openalex_authorships SET person_id = %s WHERE id = %s",
                        (person_id, a["authorship_id"]))
        elif src == "wos":
            cur.execute("UPDATE wos_authorships SET person_id = %s WHERE id = %s",
                        (person_id, a["authorship_id"]))


def add_identifiers(cur, person_id, authorships):
    """Ajoute les identifiants (ORCID, idHAL) d'un groupe d'authorships à la personne."""
    orcids = set()
    idhals = set()
    for a in authorships:
        if a.get("orcid"):
            orcids.add(a["orcid"])
        if a.get("idhal"):
            idhals.add(a["idhal"])

    for orcid in orcids:
        cur.execute("""
            INSERT INTO person_identifiers (person_id, id_type, id_value, source)
            VALUES (%s, 'orcid', %s, 'auto')
            ON CONFLICT (id_type, id_value) DO NOTHING
        """, (person_id, orcid))

    for idhal in idhals:
        cur.execute("""
            INSERT INTO person_identifiers (person_id, id_type, id_value, source)
            VALUES (%s, 'idhal', %s, 'auto')
            ON CONFLICT (id_type, id_value) DO NOTHING
        """, (person_id, idhal))


def add_name_form(cur, person_id, full_name):
    """Ajoute une forme de nom à person_name_forms si elle n'existe pas déjà."""
    if not full_name or not full_name.strip():
        return
    norm = normalize_name(full_name)
    if not norm:
        return
    cur.execute("""
        INSERT INTO person_name_forms (name_form, name_form_normalized, person_ids)
        VALUES (%s, %s, ARRAY[%s])
        ON CONFLICT (name_form_normalized) DO UPDATE
        SET person_ids = (
            SELECT array_agg(DISTINCT x)
            FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
        )
    """, (full_name.strip(), norm, person_id, person_id))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def get_all_unlinked_authorships(cur):
    """Récupère toutes les authorships UCA sans person_id, toutes sources."""
    # HAL
    cur.execute("""
        SELECT has.id AS authorship_id, 'hal' AS source,
               ha.full_name, ha.last_name, ha.first_name,
               ha.orcid, ha.idhal,
               ha.id AS hal_author_id,
               (ha.hal_person_id IS NOT NULL) AS has_hal_person_id,
               ha.hal_person_id,
               hd.publication_id
        FROM hal_authorships has
        JOIN hal_authors ha ON ha.id = has.hal_author_id
        JOIN hal_documents hd ON hd.id = has.hal_document_id
        WHERE has.person_id IS NULL
          AND has.is_uca = TRUE
          AND hd.publication_id IS NOT NULL
    """)
    hal_rows = cur.fetchall()

    # OpenAlex
    cur.execute("""
        SELECT oas.id AS authorship_id, 'openalex' AS source,
               oas.raw_author_name AS full_name,
               NULL::text AS orcid, NULL::text AS idhal,
               NULL::int AS hal_author_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               od.publication_id
        FROM openalex_authorships oas
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        WHERE oas.person_id IS NULL
          AND oas.is_uca = TRUE
          AND oas.raw_author_name IS NOT NULL
          AND od.publication_id IS NOT NULL
    """)
    oa_rows = cur.fetchall()

    # WoS
    cur.execute("""
        SELECT was.id AS authorship_id, 'wos' AS source,
               wa.full_name, wa.last_name, wa.first_name,
               wa.orcid, NULL::text AS idhal,
               NULL::int AS hal_author_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               wd.publication_id
        FROM wos_authorships was
        JOIN wos_authors wa ON wa.id = was.wos_author_id
        JOIN wos_documents wd ON wd.id = was.wos_document_id
        WHERE was.person_id IS NULL
          AND was.is_uca = TRUE
          AND wd.publication_id IS NOT NULL
    """)
    wos_rows = cur.fetchall()

    # Enrichir avec last_name/first_name parsés pour OA
    all_rows = []
    for r in hal_rows + oa_rows + wos_rows:
        r = dict(r)
        if not r.get("last_name"):
            r["last_name"], r["first_name"] = parse_raw_author_name(r["full_name"])
        r["last_norm"] = normalize_name(r["last_name"])
        r["first_norm"] = normalize_name(r["first_name"])
        r["pub_ids"] = [r["publication_id"]] if r["publication_id"] else []
        all_rows.append(r)

    return all_rows


def load_name_form_map(cur):
    """Charge person_name_forms (formes pointant vers une seule personne)."""
    cur.execute("""
        SELECT name_form_normalized, person_ids FROM person_name_forms
        WHERE array_length(person_ids, 1) = 1
          AND name_form_normalized IS NOT NULL
    """)
    result = {}
    for r in cur.fetchall():
        result[r["name_form_normalized"]] = r["person_ids"][0]
    return result


def load_existing_persons(cur):
    """Charge les personnes existantes avec noms normalisés et publications."""
    cur.execute("""
        SELECT p.id AS person_id,
               p.last_name_normalized, p.first_name_normalized,
               array_agg(DISTINCT pub_id) FILTER (WHERE pub_id IS NOT NULL) AS pub_ids
        FROM persons p
        LEFT JOIN (
            SELECT has.person_id, hd.publication_id AS pub_id
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            WHERE has.person_id IS NOT NULL AND hd.publication_id IS NOT NULL
            UNION
            SELECT oas.person_id, od.publication_id AS pub_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE oas.person_id IS NOT NULL AND od.publication_id IS NOT NULL
            UNION
            SELECT was.person_id, wd.publication_id AS pub_id
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            WHERE was.person_id IS NOT NULL AND wd.publication_id IS NOT NULL
        ) author_pubs ON author_pubs.person_id = p.id
        WHERE p.last_name_normalized IS NOT NULL AND p.last_name_normalized != ''
        GROUP BY p.id
    """)
    return cur.fetchall()


def build_person_index(existing_persons):
    """Construit un index personne par nom normalisé."""
    by_name = defaultdict(list)
    for ep in existing_persons:
        ln = ep["last_name_normalized"]
        fn = ep["first_name_normalized"] or ""
        if ln:
            by_name[(ln, fn)].append({
                "person_id": ep["person_id"],
                "last_norm": ln,
                "first_norm": fn,
                "pub_ids": set(ep["pub_ids"]) if ep["pub_ids"] else set(),
            })
    return by_name


def find_compatible_person(a, person_index, require_copub=True):
    """Cherche une personne compatible (nom compatible, optionnellement co-publication).
    Retourne person_id si match unique, None sinon.
    """
    ln, fn = a["last_norm"], a["first_norm"]
    if not ln:
        return None
    author_pubs = set(a.get("pub_ids", []))

    matched_pid = None
    # Chercher dans les noms proches (même premier caractère du nom)
    for (pln, pfn), candidates in person_index.items():
        if not names_compatible(ln, fn, pln, pfn):
            continue
        for ep in candidates:
            if require_copub and not (author_pubs & ep["pub_ids"]):
                continue
            if matched_pid is not None and matched_pid != ep["person_id"]:
                return None  # Ambiguïté
            matched_pid = ep["person_id"]

    return matched_pid


def find_exact_person(a, person_index):
    """Cherche une personne avec nom normalisé exactement identique.
    Retourne person_id si un seul candidat, None sinon.
    """
    ln, fn = a["last_norm"], a["first_norm"]
    if not ln or not fn:
        return None

    candidates = person_index.get((ln, fn), [])
    if not candidates:
        return None

    distinct_pids = set(ep["person_id"] for ep in candidates)
    if len(distinct_pids) == 1:
        return distinct_pids.pop()
    return None


# ---------------------------------------------------------------------------
# Main algorithm
# ---------------------------------------------------------------------------

def run(dry_run=False):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    all_authorships = get_all_unlinked_authorships(cur)
    logger.info(f"{len(all_authorships)} authorships UCA non rattachées (toutes sources)")

    linked_ids = set()  # (source, authorship_id)
    stats = {"pass0": 0, "pass1": 0, "pass2": 0, "pass3": 0, "pass4_created": 0,
             "pass4_merged": 0, "pass5_created": 0, "pass5_merged": 0}

    # ── Passe 0 : Comptes HAL ──
    logger.info("\n--- Passe 0 : comptes HAL ---")

    # Grouper par hal_person_id
    by_hal_pid = defaultdict(list)
    for a in all_authorships:
        if a["source"] == "hal" and a["has_hal_person_id"]:
            by_hal_pid[a["hal_person_id"]].append(a)

    # Charger les hal_authors déjà liés à une personne
    cur.execute("""
        SELECT ha.hal_person_id, ha.person_id
        FROM hal_authors ha
        WHERE ha.hal_person_id IS NOT NULL AND ha.person_id IS NOT NULL
    """)
    hal_person_map = {r["hal_person_id"]: r["person_id"] for r in cur.fetchall()}

    p0_linked = 0
    p0_created = 0
    for hal_pid, group in by_hal_pid.items():
        existing_pid = hal_person_map.get(hal_pid)
        if existing_pid:
            if not dry_run:
                link_to_person(cur, existing_pid, group)
            p0_linked += len(group)
        else:
            last, first = pick_best_name(group)
            if not dry_run:
                pid = create_person(cur, last, first)
                link_to_person(cur, pid, group)
                add_identifiers(cur, pid, group)
            p0_created += 1
            p0_linked += len(group)
        for a in group:
            linked_ids.add((a["source"], a["authorship_id"]))

    stats["pass0"] = p0_linked
    logger.info(f"  {p0_created} personnes créées, {p0_linked} authorships rattachées")

    # ── Passe 1 : Lookup person_name_forms ──
    logger.info("\n--- Passe 1 : person_name_forms ---")

    name_form_map = load_name_form_map(cur)
    p1_linked = 0
    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue
        ln, fn = a["last_norm"], a["first_norm"]
        if not ln:
            continue
        # Essayer les deux ordres
        for form in [f"{fn} {ln}", f"{ln} {fn}"]:
            pid = name_form_map.get(form)
            if pid:
                if not dry_run:
                    link_to_person(cur, pid, [a])
                linked_ids.add((a["source"], a["authorship_id"]))
                p1_linked += 1
                break

    stats["pass1"] = p1_linked
    logger.info(f"  {p1_linked} authorships rattachées")

    # ── Passe 2 : Nom + co-publication ──
    logger.info("\n--- Passe 2 : nom + co-publication ---")

    existing_persons = load_existing_persons(cur)
    person_index = build_person_index(existing_persons)

    p2_linked = 0
    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue
        pid = find_compatible_person(a, person_index, require_copub=True)
        if pid:
            if not dry_run:
                link_to_person(cur, pid, [a])
            linked_ids.add((a["source"], a["authorship_id"]))
            p2_linked += 1
            # Mettre à jour l'index
            for candidates in person_index.values():
                for ep in candidates:
                    if ep["person_id"] == pid:
                        ep["pub_ids"].update(a.get("pub_ids", []))

    stats["pass2"] = p2_linked
    logger.info(f"  {p2_linked} authorships rattachées")

    # ── Passe 3 : Nom seul (candidat unique) ──
    logger.info("\n--- Passe 3 : nom seul ---")

    # Recharger l'index après les modifications
    existing_persons = load_existing_persons(cur)
    person_index = build_person_index(existing_persons)

    p3_linked = 0
    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue
        pid = find_exact_person(a, person_index)
        if pid:
            if not dry_run:
                link_to_person(cur, pid, [a])
            linked_ids.add((a["source"], a["authorship_id"]))
            p3_linked += 1

    stats["pass3"] = p3_linked
    logger.info(f"  {p3_linked} authorships rattachées")

    # ── Passe 4 : Groupement orphelins par nom + co-publication ──
    logger.info("\n--- Passe 4 : groupement orphelins ---")

    remaining = [a for a in all_authorships
                 if (a["source"], a["authorship_id"]) not in linked_ids]

    # Grouper par (last_norm, first_norm)
    by_name = defaultdict(list)
    for a in remaining:
        if a["last_norm"] and a["first_norm"]:
            by_name[(a["last_norm"], a["first_norm"])].append(a)

    # Recharger l'index pour la vérification avant création
    existing_persons = load_existing_persons(cur)
    person_index = build_person_index(existing_persons)

    p4_created = 0
    p4_merged = 0
    for name_key, group in by_name.items():
        if len(group) < 2:
            continue

        # Union-find par co-publication
        pub_to_indices = defaultdict(set)
        for i, a in enumerate(group):
            for pub_id in a.get("pub_ids", []):
                pub_to_indices[pub_id].add(i)

        parent = list(range(len(group)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for pub_id, indices in pub_to_indices.items():
            indices = list(indices)
            for i in range(1, len(indices)):
                union(indices[0], indices[i])

        components = defaultdict(list)
        for i, a in enumerate(group):
            components[find(i)].append(a)

        for comp in components.values():
            if len(comp) < 2:
                continue

            # Avant de créer : vérifier s'il existe une personne compatible + co-pub
            all_pubs = set()
            for a in comp:
                all_pubs.update(a.get("pub_ids", []))

            # Créer un authorship synthétique pour la recherche
            representative = comp[0].copy()
            representative["pub_ids"] = list(all_pubs)
            matched_pid = find_compatible_person(representative, person_index, require_copub=True)

            if matched_pid:
                if not dry_run:
                    link_to_person(cur, matched_pid, comp)
                    for a in comp:
                        add_name_form(cur, matched_pid, a["full_name"])
                p4_merged += len(comp)
            else:
                last, first = pick_best_name(comp)
                if not dry_run:
                    pid = create_person(cur, last, first)
                    link_to_person(cur, pid, comp)
                    add_identifiers(cur, pid, comp)
                    for a in comp:
                        add_name_form(cur, pid, a["full_name"])
                p4_created += 1

            for a in comp:
                linked_ids.add((a["source"], a["authorship_id"]))

    stats["pass4_created"] = p4_created
    stats["pass4_merged"] = p4_merged
    logger.info(f"  {p4_created} personnes créées, {p4_merged} rattachées à existantes")

    # ── Passe 5 : Singletons ──
    logger.info("\n--- Passe 5 : singletons ---")

    # Recharger l'index
    existing_persons = load_existing_persons(cur)
    person_index = build_person_index(existing_persons)

    remaining2 = [a for a in all_authorships
                  if (a["source"], a["authorship_id"]) not in linked_ids]

    p5_created = 0
    p5_merged = 0
    for a in remaining2:
        if not a["last_norm"]:
            continue

        # Avant de créer : vérifier s'il existe une personne compatible + co-pub
        matched_pid = find_compatible_person(a, person_index, require_copub=True)
        if matched_pid:
            if not dry_run:
                link_to_person(cur, matched_pid, [a])
                add_name_form(cur, matched_pid, a["full_name"])
            p5_merged += 1
        else:
            last = a["last_name"] or a["full_name"] or "?"
            first = a["first_name"] or ""
            if not dry_run:
                pid = create_person(cur, last, first)
                link_to_person(cur, pid, [a])
                add_identifiers(cur, pid, [a])
                add_name_form(cur, pid, a["full_name"])
            p5_created += 1

        linked_ids.add((a["source"], a["authorship_id"]))

    stats["pass5_created"] = p5_created
    stats["pass5_merged"] = p5_merged
    logger.info(f"  {p5_created} personnes créées, {p5_merged} rattachées à existantes")

    # ── Résumé ──
    total_created = stats["pass0"] + stats["pass4_created"] + stats["pass5_created"]
    total_linked = sum(stats.values())
    unlinked = len(all_authorships) - len(linked_ids)

    logger.info(f"\n=== Résumé ===")
    logger.info(f"  Passe 0 (comptes HAL)     : {stats['pass0']} rattachées")
    logger.info(f"  Passe 1 (name_forms)      : {stats['pass1']} rattachées")
    logger.info(f"  Passe 2 (nom+co-pub)      : {stats['pass2']} rattachées")
    logger.info(f"  Passe 3 (nom seul)        : {stats['pass3']} rattachées")
    logger.info(f"  Passe 4 (groupement)      : {stats['pass4_created']} créées, {stats['pass4_merged']} rattachées")
    logger.info(f"  Passe 5 (singletons)      : {stats['pass5_created']} créées, {stats['pass5_merged']} rattachées")
    logger.info(f"  Non résolues              : {unlinked}")

    if dry_run:
        conn.rollback()
        logger.info("\n  (dry-run — rien n'a été modifié)")
    else:
        conn.commit()
        logger.info("\n  ✓ Appliqué.")
        logger.info("  → Lancer build_authorships.py pour propager is_uca/structure_ids")

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Crée des personnes à partir des authorships sources UCA"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans modifier la base")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
