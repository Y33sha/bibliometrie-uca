"""
Crée des entités Personnes à partir des authorships UCA non rattachées.

Passe 1  : Regroupement par ORCID (même ORCID → même personne)
Passe 1b : Rattachement aux personnes existantes par nom strict + co-publication
Passe 2  : Regroupement par nom strict + co-publication entre auteurs restants
            (même publi + même nom → même personne, sauf si ORCIDs différents)
Passe 3  : Singletons (authorship UCA isolée → une personne)
Passe 3b : Cross-link — rattache les auteurs non-UCA homonymes sur les mêmes
            publications que les personnes déjà liées (comble les trous inter-sources)
Passe 4  : Propagation vers authorships (table de vérité) — populate_uca_flags étape 4

Usage:
    python create_persons_from_authorships.py              # exécuter
    python create_persons_from_authorships.py --dry-run    # dry-run
"""

import argparse
import logging
import os
import sys
import unicodedata
import re
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def normalize_name(name):
    """Normalise un nom pour comparaison."""
    if not name:
        return ""
    # Remplacer les tirets Unicode (U+2010 à U+2015) par un tiret ASCII
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015]", "-", name)
    text = unicodedata.normalize("NFKD", text.lower().strip())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z\s-]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def get_unlinked_uca_authors(cur):
    """Récupère tous les auteurs UCA non rattachés à une personne."""
    # HAL authors
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

    # OpenAlex authors
    cur.execute("""
        SELECT oa.id, 'openalex' AS source, oa.full_name, oa.last_name, oa.first_name,
               oa.orcid, NULL::text AS idhal,
               array_agg(DISTINCT od.publication_id) FILTER (WHERE od.publication_id IS NOT NULL) AS pub_ids,
               COUNT(DISTINCT od.publication_id) FILTER (WHERE od.publication_id IS NOT NULL) AS pub_count
        FROM openalex_authors oa
        JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        WHERE oa.person_id IS NULL
          AND oas.is_uca = TRUE
        GROUP BY oa.id
    """)
    oa_authors = cur.fetchall()

    # WoS authors
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

    return hal_authors + oa_authors + wos_authors


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
            cur.execute("UPDATE openalex_authors SET person_id = %s, updated_at = now() WHERE id = %s",
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
    """Étape 4 : propager person_id vers la table authorships (table de vérité).

    structure_ids = périmètre large (UCA + labos tutellés + partenaires)
    is_uca = TRUE si au moins une structure du périmètre restreint (UCA + labos tutellés)
    """

    # Reset
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
                   oa.person_id,
                   oas.structure_ids AS struct_ids,
                   oas.is_uca AS src_is_uca
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
            WHERE oas.structure_ids IS NOT NULL
              AND od.publication_id IS NOT NULL
              AND oa.person_id IS NOT NULL
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

    # Stats finales
    cur.execute("SELECT COUNT(*) FROM authorships WHERE is_uca = TRUE")
    total_uca = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM authorships WHERE structure_ids IS NOT NULL")
    total_structs = cur.fetchone()["count"]
    logger.info(f"  Total authorships is_uca=TRUE : {total_uca}")
    logger.info(f"  Total authorships avec structure_ids : {total_structs}")


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
    # Personnes existantes avec leurs publications (via hal_authors et openalex_authors déjà liés)
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
            SELECT oa.person_id, od.publication_id AS pub_id
            FROM openalex_authors oa
            JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE oa.person_id IS NOT NULL AND od.publication_id IS NOT NULL
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


def run(dry_run=False):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    logger.info("Récupération des auteurs UCA non rattachés…")
    authors = get_unlinked_uca_authors(cur)
    logger.info(f"  {len(authors)} auteurs UCA non rattachés")

    # ── Passe 1 : regroupement par ORCID ──
    logger.info("\n=== Passe 1 : regroupement par ORCID ===")

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
    linked_ids = set()  # track author (source, id) that got linked

    for orcid, group in by_orcid.items():
        # Vérifier si une personne existe déjà avec cet ORCID
        existing_pid = check_existing_person_by_orcid(cur, orcid)

        if existing_pid:
            # Rattacher à la personne existante
            if not dry_run:
                link_authors_to_person(cur, existing_pid, group)
                add_identifiers(cur, existing_pid, group)
            p1_linked_existing += 1
            p1_authors_linked += len(group)
        else:
            # Créer une nouvelle personne
            last, first = pick_best_name(group)
            if not dry_run:
                pid = create_person(cur, last, first)
                link_authors_to_person(cur, pid, group)
                add_identifiers(cur, pid, group)
            p1_created += 1
            p1_authors_linked += len(group)

        for a in group:
            linked_ids.add((a["source"], a["id"]))

    logger.info(f"  {len(by_orcid)} ORCIDs distincts")
    logger.info(f"  {p1_linked_existing} rattachés à des personnes existantes")
    logger.info(f"  {p1_created} nouvelles personnes créées")
    logger.info(f"  {p1_authors_linked} auteurs rattachés")

    # ── Passe 1b : rattachement aux personnes existantes par nom + co-publication ──
    logger.info("\n=== Passe 1b : rattachement aux personnes existantes (nom + co-publication) ===")

    remaining_1b = [a for a in no_orcid if (a["source"], a["id"]) not in linked_ids]
    logger.info(f"  {len(remaining_1b)} auteurs restants sans ORCID")

    # Charger les personnes existantes avec leurs publications
    existing_persons = get_existing_persons_by_name(cur)

    # Index par (last_norm, first_norm) → liste de {person_id, pub_ids}
    existing_by_name = defaultdict(list)
    for ep in existing_persons:
        if ep["last_name_normalized"] and ep["first_name_normalized"]:
            key = (ep["last_name_normalized"], ep["first_name_normalized"])
            existing_by_name[key].append({
                "person_id": ep["person_id"],
                "pub_ids": set(ep["pub_ids"]) if ep["pub_ids"] else set(),
            })

    p1b_linked = 0
    p1b_authors_linked = 0

    for a in remaining_1b:
        if (a["source"], a["id"]) in linked_ids:
            continue
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        if not last_norm or not first_norm:
            continue

        candidates = existing_by_name.get((last_norm, first_norm), [])
        if not candidates:
            continue

        author_pubs = set(a["pub_ids"]) if a["pub_ids"] else set()
        if not author_pubs:
            continue

        # Chercher une personne existante qui partage au moins une publication
        matched_person = None
        for ep in candidates:
            if author_pubs & ep["pub_ids"]:  # intersection non vide
                if matched_person is not None and matched_person != ep["person_id"]:
                    # Ambiguïté : plusieurs personnes existantes matchent → ne pas rattacher
                    matched_person = None
                    break
                matched_person = ep["person_id"]

        if matched_person:
            if not dry_run:
                link_authors_to_person(cur, matched_person, [a])
                add_identifiers(cur, matched_person, [a])
            linked_ids.add((a["source"], a["id"]))
            p1b_authors_linked += 1

    # Compter les personnes distinctes rattachées
    logger.info(f"  {p1b_authors_linked} auteurs rattachés à des personnes existantes")

    # ── Passe 2 : nom strict + co-publication (entre auteurs non rattachés) ──
    logger.info("\n=== Passe 2 : nom strict + co-publication ===")

    remaining = [a for a in no_orcid if (a["source"], a["id"]) not in linked_ids]
    logger.info(f"  {len(remaining)} auteurs restants sans ORCID")

    # Grouper par nom normalisé
    by_name = defaultdict(list)
    for a in remaining:
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        if last_norm and first_norm:
            by_name[(last_norm, first_norm)].append(a)
        else:
            # Pas de nom exploitable — sera traité en passe 3
            pass

    p2_created = 0
    p2_authors_linked = 0

    for name_key, group in by_name.items():
        if len(group) == 1:
            # Un seul auteur avec ce nom → passe 3 (singleton)
            continue

        # Chercher les sous-groupes par co-publication (composantes connexes)
        # Deux auteurs sont dans le même groupe s'ils partagent au moins une publication
        pub_to_authors = defaultdict(set)
        for i, a in enumerate(group):
            if a["pub_ids"]:
                for pub_id in a["pub_ids"]:
                    pub_to_authors[pub_id].add(i)

        # Union-Find pour grouper les auteurs connectés
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

        # Extraire les composantes connexes (seulement celles avec > 1 auteur)
        components = defaultdict(list)
        for i, a in enumerate(group):
            components[find(i)].append(a)

        for comp_authors in components.values():
            if len(comp_authors) <= 1:
                continue

            # Vérification : pas d'ORCIDs conflictuels (normalement pas d'ORCID ici,
            # mais sécurité au cas où)
            orcids = set(a["orcid"] for a in comp_authors if a.get("orcid"))
            if len(orcids) > 1:
                logger.warning(f"  ⚠ Conflit ORCID pour {name_key}: {orcids} — ignoré")
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

    logger.info(f"  {p2_created} nouvelles personnes créées")
    logger.info(f"  {p2_authors_linked} auteurs rattachés")

    # ── Passe 3 : singletons ──
    logger.info("\n=== Passe 3 : singletons ===")

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

    logger.info(f"  {p3_created} personnes créées (singletons)")

    # ── Passe 3b : cross-link (auteurs non rattachés homonymes sur mêmes publications) ──
    logger.info("\n=== Passe 3b : cross-link inter-sources ===")

    # Charger les personnes liées avec leurs publications et noms normalisés
    existing_persons_3b = get_existing_persons_by_name(cur)

    # Index par (last_norm, first_norm) → liste de {person_id, pub_ids}
    existing_by_name_3b = defaultdict(list)
    for ep in existing_persons_3b:
        if ep["last_name_normalized"] and ep["first_name_normalized"]:
            key = (ep["last_name_normalized"], ep["first_name_normalized"])
            existing_by_name_3b[key].append({
                "person_id": ep["person_id"],
                "pub_ids": set(ep["pub_ids"]) if ep["pub_ids"] else set(),
            })

    # Charger TOUS les auteurs non rattachés (pas seulement UCA)
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
        SELECT oa.id, 'openalex' AS source, oa.last_name, oa.first_name,
               array_agg(DISTINCT od.publication_id) FILTER (WHERE od.publication_id IS NOT NULL) AS pub_ids
        FROM openalex_authors oa
        JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        WHERE oa.person_id IS NULL
          AND oa.last_name IS NOT NULL AND oa.last_name != ''
          AND oa.first_name IS NOT NULL AND oa.first_name != ''
        GROUP BY oa.id
    """)
    unlinked_oa = cur.fetchall()

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

    all_unlinked = unlinked_hal + unlinked_oa + unlinked_wos
    logger.info(f"  {len(all_unlinked)} auteurs non rattachés à examiner")

    p3b_linked = 0
    p3b_skipped_ambiguous = 0

    for a in all_unlinked:
        last_norm = normalize_name(a["last_name"])
        first_norm = normalize_name(a["first_name"])
        if not last_norm or not first_norm:
            continue

        candidates = existing_by_name_3b.get((last_norm, first_norm), [])
        if not candidates:
            continue

        author_pubs = set(a["pub_ids"]) if a["pub_ids"] else set()
        if not author_pubs:
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
                add_identifiers(cur, matched_person, [a])
            p3b_linked += 1
        elif matched_person is None and candidates:
            # On a trouvé des candidats par nom mais aucune co-publication, ou ambiguïté
            # Ne compter comme ambigu que si on a eu un break (= plusieurs personnes)
            # Ici matched_person est None et il y avait des candidats avec co-publi → ambigu
            pass

    logger.info(f"  {p3b_linked} auteurs cross-linkés")

    # ── Résumé ──
    total_created = p1_created + p2_created + p3_created
    total_linked = p1_authors_linked + p1b_authors_linked + p2_authors_linked + p3_created + p3b_linked
    logger.info(f"\n=== Résumé ===")
    logger.info(f"  Personnes créées     : {total_created}")
    logger.info(f"  Rattachées existantes: {p1_linked_existing} (ORCID) + {p1b_authors_linked} (nom+co-publi)")
    logger.info(f"  Cross-linkés (3b)    : {p3b_linked}")
    logger.info(f"  Auteurs rattachés    : {total_linked}")

    # ── Passe 4 : propagation vers authorships ──
    if dry_run:
        conn.rollback()
        logger.info(f"\n  (dry-run — rien n'a été modifié)")
    else:
        logger.info("\n=== Passe 4 : propagation vers authorships ===")
        propagate_to_authorships(cur)
        conn.commit()
        logger.info("\n  ✓ Appliqué (personnes + propagation authorships).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Créer des personnes depuis les authorships UCA")
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
