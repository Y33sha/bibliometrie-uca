"""
Crée des entités Personnes à partir des authorships UCA non rattachées.

Phase A (HAL + WoS) :
  Passe 1  : Regroupement par ORCID (même ORCID → même personne)
  Passe 1b : Rattachement aux personnes existantes par nom strict + co-publication
  Passe 2  : Regroupement par nom strict + co-publication entre auteurs restants
  Passe 3  : Singletons (authorship UCA isolée → une personne)
  Passe 3b : Cross-link HAL↔WoS (auteurs non-UCA homonymes sur mêmes publications)

Phase B (OpenAlex) :
  Résolution par raw_author_name : ORCID, puis nom+co-publi, puis nom seul, puis création

Passe 4  : Propagation vers authorships (table de vérité)

Les entités openalex_authors ne participent PAS à la résolution de personnes.
Seuls raw_author_name et raw_orcid de openalex_authorships sont utilisés.

Usage:
    python create_persons_from_authorships.py              # exécuter
    python create_persons_from_authorships.py --dry-run    # dry-run
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


def name_keys_for_oa(a):
    """Retourne les clés (last_norm, first_norm) à essayer pour un authorship OA.
    Tente l'ordre normal, puis l'ordre inversé si le raw_name contient une virgule.
    """
    ln = normalize_name(a["last_name"])
    fn = normalize_name(a["first_name"])
    keys = []
    if ln and fn:
        keys.append((ln, fn))
    # Si le raw_name contient une virgule, tester l'inversion
    if a.get("full_name") and "," in a["full_name"] and ln and fn:
        keys.append((fn, ln))
    return keys


def get_unlinked_hal_wos_authors(cur):
    """Récupère les auteurs HAL + WoS UCA non rattachés."""
    cur.execute("""
        SELECT ha.id, 'hal' AS source, ha.full_name, ha.last_name, ha.first_name,
               ha.orcid, ha.idhal,
               array_agg(DISTINCT hd.publication_id) FILTER (WHERE hd.publication_id IS NOT NULL) AS pub_ids,
               COUNT(DISTINCT hd.publication_id) FILTER (WHERE hd.publication_id IS NOT NULL) AS pub_count
        FROM hal_authors ha
        JOIN hal_authorships has ON has.hal_author_id = ha.id
        JOIN hal_documents hd ON hd.id = has.hal_document_id
        WHERE ha.person_id IS NULL
          AND has.is_uca = TRUE
        GROUP BY ha.id
    """)
    hal_authors = cur.fetchall()

    cur.execute("""
        SELECT wa.id, 'wos' AS source, wa.full_name, wa.last_name, wa.first_name,
               wa.orcid, NULL::text AS idhal,
               array_agg(DISTINCT wd.publication_id) FILTER (WHERE wd.publication_id IS NOT NULL) AS pub_ids,
               COUNT(DISTINCT wd.publication_id) FILTER (WHERE wd.publication_id IS NOT NULL) AS pub_count
        FROM wos_authors wa
        JOIN wos_authorships was ON was.wos_author_id = wa.id
        JOIN wos_documents wd ON wd.id = was.wos_document_id
        WHERE wa.person_id IS NULL
          AND was.is_uca = TRUE
        GROUP BY wa.id
    """)
    wos_authors = cur.fetchall()

    return hal_authors + wos_authors


def get_unlinked_oa_authorships(cur):
    """Récupère les authorships OpenAlex UCA non rattachées (raw_author_name)."""
    cur.execute("""
        SELECT oas.id, 'openalex' AS source,
               oas.raw_author_name AS full_name,
               oas.raw_orcid AS orcid,
               NULL::text AS idhal,
               od.publication_id AS pub_id
        FROM openalex_authorships oas
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        WHERE oas.person_id IS NULL
          AND oas.is_uca = TRUE
          AND oas.raw_author_name IS NOT NULL
          AND od.publication_id IS NOT NULL
    """)
    rows = cur.fetchall()
    # Enrichir avec last_name/first_name parsés
    for r in rows:
        r["last_name"], r["first_name"] = parse_raw_author_name(r["full_name"])
        r["pub_ids"] = [r["pub_id"]] if r["pub_id"] else []
        r["pub_count"] = 1 if r["pub_id"] else 0
    return rows


def pick_best_name(authors):
    """Choisit le meilleur nom parmi un groupe d'auteurs (celui avec le plus de publis)."""
    best = max(authors, key=lambda a: a["pub_count"])
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


def link_authors_to_person(cur, person_id, authors):
    """Rattache une liste d'auteurs à une personne."""
    for a in authors:
        if a["source"] == "hal":
            cur.execute("UPDATE hal_authors SET person_id = %s, updated_at = now() WHERE id = %s",
                        (person_id, a["id"]))
        elif a["source"] == "openalex":
            cur.execute("UPDATE openalex_authorships SET person_id = %s WHERE id = %s",
                        (person_id, a["id"]))
        elif a["source"] == "wos":
            cur.execute("UPDATE wos_authors SET person_id = %s, updated_at = now() WHERE id = %s",
                        (person_id, a["id"]))


def add_identifiers(cur, person_id, authors):
    """Ajoute les identifiants (ORCID, idHAL) d'un groupe d'auteurs à la personne."""
    orcids = set()
    idhals = set()
    for a in authors:
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


def propagate_to_authorships(cur):
    """Étape 4 : propager person_id vers la table authorships (table de vérité)."""

    cur.execute("UPDATE authorships SET is_uca = FALSE, structure_ids = NULL")
    reset_count = cur.rowcount
    logger.info(f"  Reset {reset_count} authorships")

    # 4a. Depuis HAL
    cur.execute("""
        WITH uca_perimeter AS (
            SELECT s.id FROM structures s WHERE s.code = 'uca'
            UNION
            SELECT sr.child_id FROM structure_relations sr
            JOIN structures s ON s.id = sr.parent_id
            WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
        ),
        hal_data AS (
            SELECT hd.publication_id,
                   ha.person_id,
                   array_agg(DISTINCT sid) AS all_struct_ids,
                   bool_or(sid IN (SELECT id FROM uca_perimeter)) AS has_uca
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            JOIN hal_authors ha ON ha.id = has.hal_author_id,
            LATERAL unnest(has.structure_ids) AS sid
            WHERE has.structure_ids IS NOT NULL
              AND hd.publication_id IS NOT NULL
              AND ha.person_id IS NOT NULL
            GROUP BY hd.publication_id, ha.person_id
        )
        UPDATE authorships a
        SET structure_ids = hd.all_struct_ids,
            is_uca = hd.has_uca,
            updated_at = now()
        FROM hal_data hd
        WHERE a.publication_id = hd.publication_id
          AND a.person_id = hd.person_id
          AND a.person_id IS NOT NULL
    """)
    hal_count = cur.rowcount
    logger.info(f"  {hal_count} authorships mises à jour depuis HAL")

    # 4b. Depuis OpenAlex
    cur.execute("""
        WITH oa_data AS (
            SELECT od.publication_id,
                   oas.person_id,
                   oas.structure_ids AS struct_ids,
                   oas.is_uca AS src_is_uca
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE oas.structure_ids IS NOT NULL
              AND od.publication_id IS NOT NULL
              AND oas.person_id IS NOT NULL
        )
        UPDATE authorships a
        SET structure_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(COALESCE(a.structure_ids, '{}') || od.struct_ids) AS x
            ),
            is_uca = a.is_uca OR od.src_is_uca,
            updated_at = now()
        FROM oa_data od
        WHERE a.publication_id = od.publication_id
          AND a.person_id = od.person_id
          AND a.person_id IS NOT NULL
    """)
    oa_count = cur.rowcount
    logger.info(f"  {oa_count} authorships mises à jour depuis OpenAlex")

    # 4c. Depuis WoS
    cur.execute("""
        WITH wos_data AS (
            SELECT wd.publication_id,
                   wa.person_id,
                   was.structure_ids AS struct_ids,
                   was.is_uca AS src_is_uca
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            JOIN wos_authors wa ON wa.id = was.wos_author_id
            WHERE was.structure_ids IS NOT NULL
              AND wd.publication_id IS NOT NULL
              AND wa.person_id IS NOT NULL
        )
        UPDATE authorships a
        SET structure_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(COALESCE(a.structure_ids, '{}') || wd.struct_ids) AS x
            ),
            is_uca = a.is_uca OR wd.src_is_uca,
            updated_at = now()
        FROM wos_data wd
        WHERE a.publication_id = wd.publication_id
          AND a.person_id = wd.person_id
          AND a.person_id IS NOT NULL
    """)
    wos_count = cur.rowcount
    logger.info(f"  {wos_count} authorships mises à jour depuis WoS")

    cur.execute("SELECT COUNT(*) FROM authorships WHERE is_uca = TRUE")
    total_uca = cur.fetchone()["count"]
    logger.info(f"  Total authorships is_uca=TRUE : {total_uca}")


def check_existing_person_by_orcid(cur, orcid):
    """Vérifie si une personne existe déjà avec cet ORCID."""
    cur.execute("""
        SELECT person_id FROM person_identifiers
        WHERE id_type = 'orcid' AND id_value = %s AND status != 'rejected'
        LIMIT 1
    """, (orcid,))
    row = cur.fetchone()
    return row["person_id"] if row else None


def get_existing_persons_by_name(cur):
    """Récupère les personnes existantes avec leurs noms normalisés et leurs publication_ids."""
    cur.execute("""
        SELECT p.id AS person_id,
               p.last_name_normalized, p.first_name_normalized,
               array_agg(DISTINCT pub_id) FILTER (WHERE pub_id IS NOT NULL) AS pub_ids
        FROM persons p
        LEFT JOIN (
            SELECT ha.person_id, hd.publication_id AS pub_id
            FROM hal_authors ha
            JOIN hal_authorships has ON has.hal_author_id = ha.id
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            WHERE ha.person_id IS NOT NULL AND hd.publication_id IS NOT NULL
            UNION
            SELECT oas.person_id, od.publication_id AS pub_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE oas.person_id IS NOT NULL AND od.publication_id IS NOT NULL
            UNION
            SELECT wa.person_id, wd.publication_id AS pub_id
            FROM wos_authors wa
            JOIN wos_authorships was ON was.wos_author_id = wa.id
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            WHERE wa.person_id IS NOT NULL AND wd.publication_id IS NOT NULL
        ) author_pubs ON author_pubs.person_id = p.id
        WHERE p.last_name_normalized IS NOT NULL
          AND p.last_name_normalized != ''
          AND p.first_name_normalized IS NOT NULL
          AND p.first_name_normalized != ''
        GROUP BY p.id
    """)
    return cur.fetchall()


def run_phase_a(cur, dry_run=False):
    """Phase A : HAL + WoS — création et liaison de personnes."""

    logger.info("=== PHASE A : HAL + WoS ===")
    authors = get_unlinked_hal_wos_authors(cur)
    logger.info(f"  {len(authors)} auteurs HAL/WoS UCA non rattachés")

    # ── Passe 1 : regroupement par ORCID ──
    logger.info("\n--- Passe 1 : regroupement par ORCID ---")

    by_orcid = defaultdict(list)
    no_orcid = []
    for a in authors:
        if a["orcid"]:
            by_orcid[a["orcid"]].append(a)
        else:
            no_orcid.append(a)

    p1_created = 0
    p1_linked_existing = 0
    p1_authors_linked = 0
    linked_ids = set()

    for orcid, group in by_orcid.items():
        existing_pid = check_existing_person_by_orcid(cur, orcid)

        if existing_pid:
            if not dry_run:
                link_authors_to_person(cur, existing_pid, group)
                add_identifiers(cur, existing_pid, group)
            p1_linked_existing += 1
            p1_authors_linked += len(group)
        else:
            last, first = pick_best_name(group)
            if not dry_run:
                pid = create_person(cur, last, first)
                link_authors_to_person(cur, pid, group)
                add_identifiers(cur, pid, group)
            p1_created += 1
            p1_authors_linked += len(group)

        for a in group:
            linked_ids.add((a["source"], a["id"]))

    logger.info(f"  {len(by_orcid)} ORCIDs distincts, {p1_created} créées, {p1_linked_existing} rattachées")

    # ── Passe 1b : rattachement par nom + co-publication ──
    logger.info("\n--- Passe 1b : nom + co-publication vers personnes existantes ---")

    existing_persons = get_existing_persons_by_name(cur)
    existing_by_name = defaultdict(list)
    for ep in existing_persons:
        if ep["last_name_normalized"] and ep["first_name_normalized"]:
            key = (ep["last_name_normalized"], ep["first_name_normalized"])
            existing_by_name[key].append({
                "person_id": ep["person_id"],
                "pub_ids": set(ep["pub_ids"]) if ep["pub_ids"] else set(),
            })

    p1b_linked = 0
    for a in no_orcid:
        if (a["source"], a["id"]) in linked_ids:
            continue
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        if not last_norm or not first_norm:
            continue

        author_pubs = set(a["pub_ids"]) if a["pub_ids"] else set()
        if not author_pubs:
            continue

        candidates = existing_by_name.get((last_norm, first_norm), [])
        matched_person = None
        for ep in candidates:
            if author_pubs & ep["pub_ids"]:
                if matched_person is not None and matched_person != ep["person_id"]:
                    matched_person = None
                    break
                matched_person = ep["person_id"]

        if matched_person:
            if not dry_run:
                link_authors_to_person(cur, matched_person, [a])
                add_identifiers(cur, matched_person, [a])
            linked_ids.add((a["source"], a["id"]))
            p1b_linked += 1

    logger.info(f"  {p1b_linked} auteurs rattachés")

    # ── Passe 2 : nom strict + co-publication entre non-rattachés ──
    logger.info("\n--- Passe 2 : co-publication entre non-rattachés ---")

    remaining = [a for a in no_orcid if (a["source"], a["id"]) not in linked_ids]
    by_name = defaultdict(list)
    for a in remaining:
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        if last_norm and first_norm:
            by_name[(last_norm, first_norm)].append(a)

    p2_created = 0
    p2_authors_linked = 0

    for name_key, group in by_name.items():
        if len(group) == 1:
            continue

        pub_to_authors = defaultdict(set)
        for i, a in enumerate(group):
            if a["pub_ids"]:
                for pub_id in a["pub_ids"]:
                    pub_to_authors[pub_id].add(i)

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

        for pub_id, indices in pub_to_authors.items():
            indices = list(indices)
            for i in range(1, len(indices)):
                union(indices[0], indices[i])

        components = defaultdict(list)
        for i, a in enumerate(group):
            components[find(i)].append(a)

        for comp_authors in components.values():
            if len(comp_authors) <= 1:
                continue
            orcids = set(a["orcid"] for a in comp_authors if a.get("orcid"))
            if len(orcids) > 1:
                continue

            last, first = pick_best_name(comp_authors)
            if not dry_run:
                pid = create_person(cur, last, first)
                link_authors_to_person(cur, pid, comp_authors)
                add_identifiers(cur, pid, comp_authors)
            p2_created += 1
            p2_authors_linked += len(comp_authors)
            for a in comp_authors:
                linked_ids.add((a["source"], a["id"]))

    logger.info(f"  {p2_created} personnes créées, {p2_authors_linked} auteurs rattachés")

    # ── Passe 3 : singletons ──
    logger.info("\n--- Passe 3 : singletons ---")

    singletons = [a for a in authors if (a["source"], a["id"]) not in linked_ids]
    p3_created = 0
    for a in singletons:
        last = a["last_name"] or a["full_name"] or "?"
        first = a["first_name"] or ""
        if not dry_run:
            pid = create_person(cur, last, first)
            link_authors_to_person(cur, pid, [a])
            add_identifiers(cur, pid, [a])
        p3_created += 1

    logger.info(f"  {p3_created} personnes créées")

    # ── Passe 3b : cross-link HAL↔WoS ──
    logger.info("\n--- Passe 3b : cross-link HAL↔WoS ---")

    existing_persons_3b = get_existing_persons_by_name(cur)
    existing_by_name_3b = defaultdict(list)
    for ep in existing_persons_3b:
        if ep["last_name_normalized"] and ep["first_name_normalized"]:
            key = (ep["last_name_normalized"], ep["first_name_normalized"])
            existing_by_name_3b[key].append({
                "person_id": ep["person_id"],
                "pub_ids": set(ep["pub_ids"]) if ep["pub_ids"] else set(),
            })

    cur.execute("""
        SELECT ha.id, 'hal' AS source, ha.last_name, ha.first_name,
               array_agg(DISTINCT hd.publication_id) FILTER (WHERE hd.publication_id IS NOT NULL) AS pub_ids
        FROM hal_authors ha
        JOIN hal_authorships has ON has.hal_author_id = ha.id
        JOIN hal_documents hd ON hd.id = has.hal_document_id
        WHERE ha.person_id IS NULL
          AND ha.last_name IS NOT NULL AND ha.last_name != ''
          AND ha.first_name IS NOT NULL AND ha.first_name != ''
        GROUP BY ha.id
    """)
    unlinked_hal = cur.fetchall()

    cur.execute("""
        SELECT wa.id, 'wos' AS source, wa.last_name, wa.first_name,
               array_agg(DISTINCT wd.publication_id) FILTER (WHERE wd.publication_id IS NOT NULL) AS pub_ids
        FROM wos_authors wa
        JOIN wos_authorships was ON was.wos_author_id = wa.id
        JOIN wos_documents wd ON wd.id = was.wos_document_id
        WHERE wa.person_id IS NULL
          AND wa.last_name IS NOT NULL AND wa.last_name != ''
          AND wa.first_name IS NOT NULL AND wa.first_name != ''
        GROUP BY wa.id
    """)
    unlinked_wos = cur.fetchall()

    p3b_linked = 0
    for a in unlinked_hal + unlinked_wos:
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        if not last_norm or not first_norm:
            continue

        candidates = existing_by_name_3b.get((last_norm, first_norm), [])
        author_pubs = set(a["pub_ids"]) if a["pub_ids"] else set()
        if not author_pubs or not candidates:
            continue

        matched_person = None
        for ep in candidates:
            if author_pubs & ep["pub_ids"]:
                if matched_person is not None and matched_person != ep["person_id"]:
                    matched_person = None
                    break
                matched_person = ep["person_id"]

        if matched_person:
            if not dry_run:
                link_authors_to_person(cur, matched_person, [a])
            p3b_linked += 1

    logger.info(f"  {p3b_linked} auteurs cross-linkés")

    return {
        "created": p1_created + p2_created + p3_created,
        "linked": p1_authors_linked + p1b_linked + p2_authors_linked + p3_created + p3b_linked,
    }


def run_phase_b(cur, dry_run=False):
    """Phase B : OpenAlex — résolution par raw_author_name."""

    logger.info("\n=== PHASE B : OpenAlex (raw_author_name) ===")

    oa_authorships = get_unlinked_oa_authorships(cur)
    logger.info(f"  {len(oa_authorships)} authorships OA UCA non rattachées")

    if not oa_authorships:
        return {"created": 0, "linked": 0}

    # Charger les personnes existantes (inclut celles créées en phase A)
    existing_persons = get_existing_persons_by_name(cur)
    existing_by_name = defaultdict(list)
    for ep in existing_persons:
        if ep["last_name_normalized"] and ep["first_name_normalized"]:
            key = (ep["last_name_normalized"], ep["first_name_normalized"])
            existing_by_name[key].append({
                "person_id": ep["person_id"],
                "pub_ids": set(ep["pub_ids"]) if ep["pub_ids"] else set(),
            })

    oa_linked_copub = 0
    oa_linked_name = 0
    linked_oa_ids = set()

    # Charger les personnes existantes (créées par phase A)
    existing_persons = get_existing_persons_by_name(cur)
    existing_by_name = defaultdict(list)
    for ep in existing_persons:
        if ep["last_name_normalized"] and ep["first_name_normalized"]:
            key = (ep["last_name_normalized"], ep["first_name_normalized"])
            existing_by_name[key].append({
                "person_id": ep["person_id"],
                "pub_ids": set(ep["pub_ids"]) if ep["pub_ids"] else set(),
            })

    # Sous-passe B1 : nom + co-publication
    logger.info("\n--- B1 : nom + co-publication ---")
    remaining = oa_authorships

    for a in remaining:
        keys = name_keys_for_oa(a)
        if not keys:
            continue

        author_pubs = set(a["pub_ids"]) if a["pub_ids"] else set()
        if not author_pubs:
            continue

        matched_person = None
        matched_candidates = None
        for key in keys:
            candidates = existing_by_name.get(key, [])
            for ep in candidates:
                if author_pubs & ep["pub_ids"]:
                    if matched_person is not None and matched_person != ep["person_id"]:
                        matched_person = None
                        matched_candidates = None
                        break
                    matched_person = ep["person_id"]
                    matched_candidates = candidates
            if matched_person:
                break

        if matched_person and matched_candidates:
            if not dry_run:
                link_authors_to_person(cur, matched_person, [a])
            linked_oa_ids.add(a["id"])
            oa_linked_copub += 1
            for ep in matched_candidates:
                if ep["person_id"] == matched_person:
                    ep["pub_ids"].update(author_pubs)

    logger.info(f"  {oa_linked_copub} liées par nom + co-publication")

    # Sous-passe B2 : nom seul (candidat unique OU tous la même personne)
    logger.info("\n--- B2 : nom seul ---")
    remaining2 = [a for a in remaining if a["id"] not in linked_oa_ids]

    for a in remaining2:
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        if not last_norm or not first_norm:
            continue

        candidates = existing_by_name.get((last_norm, first_norm), [])
        if not candidates:
            continue
        # Si tous les candidats pointent vers la même personne → match
        distinct_pids = set(ep["person_id"] for ep in candidates)
        if len(distinct_pids) == 1:
            matched_person = distinct_pids.pop()
            if not dry_run:
                link_authors_to_person(cur, matched_person, [a])
            linked_oa_ids.add(a["id"])
            oa_linked_name += 1
            candidates[0]["pub_ids"].update(set(a["pub_ids"]) if a["pub_ids"] else set())

    logger.info(f"  {oa_linked_name} liées par nom seul")

    # Sous-passe B3 : création de nouvelles personnes
    # Grouper par (last_norm, first_norm) → une seule personne par nom distinct
    # Si une personne existe déjà avec ce nom → rattacher, pas créer
    logger.info("\n--- B4 : création de nouvelles personnes ---")
    # Recharger les personnes existantes (inclut celles liées en B1-B3)
    existing_persons = get_existing_persons_by_name(cur)
    existing_by_name_b4 = defaultdict(list)
    for ep in existing_persons:
        if ep["last_name_normalized"] and ep["first_name_normalized"]:
            key = (ep["last_name_normalized"], ep["first_name_normalized"])
            existing_by_name_b4[key].append(ep["person_id"])

    remaining3 = [a for a in oa_authorships if a["id"] not in linked_oa_ids]
    b4_by_name = defaultdict(list)
    for a in remaining3:
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        b4_by_name[(last_norm, first_norm or "")].append(a)

    b4_created = 0
    b4_linked_existing = 0
    b4_linked = 0
    for (ln, fn), group in b4_by_name.items():
        # Chercher une personne existante avec ce nom
        existing_pids = set(existing_by_name_b4.get((ln, fn), []))
        if len(existing_pids) == 1:
            pid = existing_pids.pop()
            if not dry_run:
                link_authors_to_person(cur, pid, group)
            b4_linked_existing += len(group)
        else:
            last = group[0]["last_name"] or group[0]["full_name"] or "?"
            first = group[0]["first_name"] or ""
            if not dry_run:
                pid = create_person(cur, last, first)
                link_authors_to_person(cur, pid, group)
                add_identifiers(cur, pid, group)
            b4_created += 1
        b4_linked += len(group)

    logger.info(f"  {b4_created} personnes créées, {b4_linked_existing} rattachées à existantes, pour {b4_linked} authorships")

    total_created = b4_created
    total_linked = oa_linked_copub + oa_linked_name + b4_linked
    return {"created": total_created, "linked": total_linked}


def run(dry_run=False):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    stats_a = run_phase_a(cur, dry_run)
    stats_b = run_phase_b(cur, dry_run)

    logger.info(f"\n=== Résumé ===")
    logger.info(f"  Phase A (HAL/WoS) : {stats_a['created']} personnes créées, {stats_a['linked']} auteurs rattachés")
    logger.info(f"  Phase B (OpenAlex) : {stats_b['created']} personnes créées, {stats_b['linked']} auteurs rattachés")

    if dry_run:
        conn.rollback()
        logger.info(f"\n  (dry-run — rien n'a été modifié)")
    else:
        logger.info("\n=== Passe 4 : propagation vers authorships ===")
        propagate_to_authorships(cur)
        conn.commit()
        logger.info("\n  ✓ Appliqué.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Créer des personnes depuis les authorships UCA")
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
