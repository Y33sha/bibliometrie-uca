#!/usr/bin/env python3
"""
migrate_hal.py — Phase 2, étape 2.1
====================================
Lit staging_hal et peuple les nouvelles tables v2 :
  - hal_authors     (un par hal_person_id unique)
  - hal_documents   (un par halid)
  - hal_authorships (un par document × auteur, avec hal_struct_ids[])

Résout is_uca et structure_id sur les authorships via hal_structures.
Relie hal_documents aux publications existantes (par DOI, puis par
l'ancienne table publication_sources).

Usage:
    python3 migrate_hal.py                # traiter tout
    python3 migrate_hal.py --limit 100    # traiter N documents (test)
    python3 migrate_hal.py --reset        # remettre processed=FALSE sur staging_hal
"""

import argparse
import logging
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.normalize import normalize_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "migrate_hal.log")
        ),
    ],
)
logger = logging.getLogger(__name__)



def clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
    return doi if doi else None


def as_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value)


def get_title(doc: dict) -> str:
    titles = doc.get("title_s")
    if isinstance(titles, list) and titles:
        return titles[0]
    if isinstance(titles, str):
        return titles
    return doc.get("label_s", "")


def split_name(full_name: str) -> tuple[str | None, str]:
    """Sépare un nom complet en (prénom, nom). Heuristique HAL."""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return None, full_name


# =============================================================
# PEUPLEMENT DES NOUVELLES TABLES
# =============================================================

def upsert_hal_author(cur, full_name: str, hal_person_id: int | None,
                      idhal: str | None, orcid: str | None) -> int:
    """Insère ou retrouve un hal_author. Retourne hal_authors.id.

    Stratégie de lookup :
      1. Par hal_person_id (identifiant le plus fiable)
      2. Par idhal
      3. Insertion
    """
    if orcid:
        orcid = orcid.replace("https://orcid.org/", "").strip() or None

    first_name, last_name = split_name(full_name)

    # 1. Par hal_person_id
    if hal_person_id is not None:
        cur.execute(
            "SELECT id FROM hal_authors WHERE hal_person_id = %s",
            (hal_person_id,)
        )
        row = cur.fetchone()
        if row:
            # Enrichir idhal/orcid si on en sait plus
            cur.execute("""
                UPDATE hal_authors SET
                    idhal = COALESCE(hal_authors.idhal, %s),
                    orcid = COALESCE(hal_authors.orcid, %s),
                    updated_at = now()
                WHERE id = %s
            """, (idhal, orcid, row[0]))
            return row[0]

    # 2. Par idhal
    if idhal:
        cur.execute(
            "SELECT id FROM hal_authors WHERE idhal = %s",
            (idhal,)
        )
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE hal_authors SET
                    hal_person_id = COALESCE(hal_authors.hal_person_id, %s),
                    orcid = COALESCE(hal_authors.orcid, %s),
                    updated_at = now()
                WHERE id = %s
            """, (hal_person_id, orcid, row[0]))
            return row[0]

    # 3. Fallback par nom exact (auteurs sans identifiant HAL)
    # Ces auteurs n'ont pas de compte HAL ou leur identité n'est pas résolue.
    # On déduplique par nom exact, mais il faut garder en tête que ce
    # hal_author peut regrouper des publications de personnes différentes
    # (homonymes). Le champ is_reliable pourra être mis à FALSE si nécessaire.
    cur.execute("""
        SELECT id FROM hal_authors
        WHERE full_name = %s AND hal_person_id IS NULL AND idhal IS NULL
        LIMIT 1
    """, (full_name,))
    row = cur.fetchone()
    if row:
        return row[0]

    # 4. Insertion
    cur.execute("""
        INSERT INTO hal_authors (hal_person_id, full_name, last_name, first_name, idhal, orcid)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (hal_person_id, full_name, last_name, first_name, idhal, orcid))
    return cur.fetchone()[0]


def insert_hal_document(cur, staging_id: int, hal_id: str, doc: dict) -> int | None:
    """Insère un hal_document. Retourne hal_documents.id ou None si déjà existant."""

    # Vérifier si déjà migré
    cur.execute("SELECT id FROM hal_documents WHERE halid = %s", (hal_id,))
    row = cur.fetchone()
    if row:
        return row[0]

    title = get_title(doc)
    if not title:
        return None

    doi = clean_doi(as_str(doc.get("doiId_s")))
    pub_year = doc.get("producedDateY_i")
    doc_type = doc.get("docType_s")

    # Collections : le document peut figurer dans plusieurs collections.
    # Le champ collection du staging est la collection de la requête d'extraction.
    # On cherche aussi dans les données brutes si d'autres collections sont listées.
    collections = []
    # collCode_s contient toutes les collections du document
    coll_codes = doc.get("collCode_s")
    if isinstance(coll_codes, list):
        collections = list(set(coll_codes))
    elif isinstance(coll_codes, str):
        collections = [coll_codes]

    cur.execute("""
        INSERT INTO hal_documents (halid, doi, title, pub_year, doc_type, collections, staging_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (hal_id, doi, title, pub_year, doc_type, collections or None, staging_id))
    return cur.fetchone()[0]


def extract_authors_and_authorships(cur, doc: dict, hal_document_id: int,
                                    max_authors: int = 200):
    """Parse les champs composés HAL pour créer les auteurs et authorships.

    Champs utilisés (tous alignés par position) :
      - authFullName_s : noms complets
      - authFullNameIdHal_fs : "Nom_FacetSep_idhal"
      - authFullNameId_fs : "Nom_FacetSep_personId"
      - authIdHasStructure_fs : affiliations auteur→structure par document
    """
    names = doc.get("authFullName_s") or []
    if not names:
        return

    # Documents avec un très grand nombre d'auteurs (physique des particules,
    # consortiums médicaux) : on stocke le document mais on skippe les authorships
    # individuels pour ne pas bloquer la migration. Seuil : 200 auteurs.
    MAX_AUTHORS = max_authors
    if len(names) > MAX_AUTHORS:
        logger.info(f"  Document avec {len(names)} auteurs → authorships skippés (seuil: {MAX_AUTHORS})")
        return

    # --- idHAL par position (authFullNameIdHal_fs) ---
    idhal_by_pos = {}
    for pos, entry in enumerate(doc.get("authFullNameIdHal_fs") or []):
        parts = entry.split("_FacetSep_")
        if len(parts) == 2 and parts[1].strip():
            idhal_by_pos[pos] = parts[1].strip()

    # --- hal_person_id par position (authFullNameId_fs) ---
    person_id_by_pos = {}
    for pos, entry in enumerate(doc.get("authFullNameId_fs") or []):
        parts = entry.split("_FacetSep_")
        if len(parts) == 2 and parts[1].strip():
            try:
                person_id_by_pos[pos] = int(parts[1].strip())
            except ValueError:
                pass

    # --- Affiliations : hal_person_id → set(hal_struct_ids) ---
    person_structs = parse_author_structures(doc)

    # --- Créer auteurs + authorships ---
    for position, name in enumerate(names):
        hal_person_id = person_id_by_pos.get(position)
        idhal = idhal_by_pos.get(position)

        author_id = upsert_hal_author(cur, name, hal_person_id, idhal, orcid=None)

        # Structures affiliées pour cet auteur sur ce document
        struct_ids = []
        if hal_person_id and hal_person_id in person_structs:
            struct_ids = sorted(person_structs[hal_person_id])

        cur.execute("""
            INSERT INTO hal_authorships
                (hal_document_id, hal_author_id, author_position, hal_struct_ids)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (hal_document_id, hal_author_id) DO UPDATE SET
                hal_struct_ids = COALESCE(EXCLUDED.hal_struct_ids, hal_authorships.hal_struct_ids)
        """, (hal_document_id, author_id, position, struct_ids or None))


def parse_author_structures(doc: dict) -> dict[int, set[int]]:
    """Parse authIdHasStructure_fs pour extraire les affiliations.

    Format : "formId-personId_FacetSep_Nom_JoinSep_structId_FacetSep_StructNom"

    Retourne : {hal_person_id: {hal_struct_id, ...}}
    """
    entries = doc.get("authIdHasStructure_fs") or []
    person_structs: dict[int, set[int]] = {}

    for entry in entries:
        join_parts = entry.split("_JoinSep_")
        if len(join_parts) != 2:
            continue

        # Gauche : "formId-personId_FacetSep_Nom"
        left_parts = join_parts[0].split("_FacetSep_")
        if not left_parts:
            continue
        dash_parts = left_parts[0].rsplit("-", 1)
        if len(dash_parts) != 2:
            continue
        try:
            person_id = int(dash_parts[1])
        except ValueError:
            continue

        # Droite : "structId_FacetSep_StructNom"
        right_parts = join_parts[1].split("_FacetSep_")
        if not right_parts:
            continue
        try:
            struct_id = int(right_parts[0])
        except ValueError:
            continue

        person_structs.setdefault(person_id, set()).add(struct_id)

    return person_structs


# =============================================================
# RÉSOLUTION UCA
# =============================================================

def resolve_uca_authorships(cur):
    """Résout is_uca et structure_ids sur tous les hal_authorships.

    Pour chaque authorship ayant des hal_struct_ids, identifie TOUTES les
    structures UCA affiliées (via hal_structures.structure_id) et les stocke
    dans structure_ids[]. is_uca = TRUE si au moins une structure UCA trouvée.

    Opère en batch sur toute la table.
    """
    logger.info("Résolution des affiliations UCA sur hal_authorships...")

    # Charger le mapping hal_struct_id → structure_id pour toutes les structures UCA
    cur.execute("""
        SELECT hs.hal_struct_id, hs.structure_id
        FROM hal_structures hs
        WHERE hs.structure_id IS NOT NULL
    """)
    uca_map = {}  # {hal_struct_id: structure_id}
    for row in cur.fetchall():
        uca_map[row[0]] = row[1]

    if not uca_map:
        logger.warning("Aucune structure HAL mappée vers une structure locale. "
                       "Avez-vous exécuté populate_hal_struct_ids.py match/apply ?")
        return

    logger.info(f"  {len(uca_map)} hal_struct_id mappés vers des structures locales")

    # Traiter tous les authorships ayant des hal_struct_ids
    cur.execute("""
        SELECT id, hal_struct_ids
        FROM hal_authorships
        WHERE hal_struct_ids IS NOT NULL
          AND array_length(hal_struct_ids, 1) > 0
    """)
    rows = cur.fetchall()
    logger.info(f"  {len(rows)} authorships avec des structures à résoudre")

    resolved = 0
    for authorship_id, struct_ids in rows:
        # Collecter TOUTES les structures UCA pour cet authorship
        resolved_ids = set()
        for sid in struct_ids:
            if sid in uca_map:
                resolved_ids.add(uca_map[sid])

        if resolved_ids:
            cur.execute("""
                UPDATE hal_authorships
                SET is_uca = TRUE, structure_ids = %s
                WHERE id = %s
            """, (sorted(resolved_ids), authorship_id))
            resolved += 1

    logger.info(f"  {resolved} authorships marqués UCA")


# =============================================================
# LIAISON PUBLICATIONS EXISTANTES
# =============================================================

def link_to_existing_publications(cur):
    """Relie les hal_documents aux publications existantes.

    Stratégie :
      1. Par DOI (match direct)
      2. Par l'ancienne table publication_sources (halid → publication_id)
      3. Par titre normalisé + année (fuzzy)
    """
    logger.info("Liaison hal_documents → publications existantes...")

    # 1. Par DOI
    cur.execute("""
        UPDATE hal_documents hd
        SET publication_id = p.id
        FROM publications p
        WHERE hd.doi IS NOT NULL
          AND hd.doi = p.doi
          AND hd.publication_id IS NULL
    """)
    by_doi = cur.rowcount
    logger.info(f"  Par DOI : {by_doi} reliés")

    # 2. Par l'ancienne table publication_sources
    cur.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'publication_sources' AND table_type = 'BASE TABLE'
    """)
    if cur.fetchone():
        cur.execute("""
            UPDATE hal_documents hd
            SET publication_id = ps.publication_id
            FROM publication_sources ps
            WHERE ps.source = 'hal'
              AND ps.source_id = hd.halid
              AND hd.publication_id IS NULL
        """)
        by_source = cur.rowcount
        logger.info(f"  Par publication_sources : {by_source} reliés")
    else:
        logger.info("  Table publication_sources absente, étape sautée")

    # 3. Par titre normalisé + année
    cur.execute("""
        UPDATE hal_documents hd
        SET publication_id = p.id
        FROM publications p
        WHERE hd.publication_id IS NULL
          AND hd.pub_year = p.pub_year
          AND hd.pub_year IS NOT NULL
          AND p.title_normalized IS NOT NULL
          AND p.title_normalized != ''
          AND p.title_normalized = (
              SELECT lower(regexp_replace(
                  translate(hd.title, 'àâäéèêëïîôùûüÿçÀÂÄÉÈÊËÏÎÔÙÛÜŸÇ',
                                       'aaaeeeeiioouuycAAÄEEEEIIOOUUUYC'),
                  '[^a-zA-Z0-9 ]', '', 'g'
              ))
          )
    """)
    by_title = cur.rowcount
    logger.info(f"  Par titre+année : {by_title} reliés")

    # Stats
    cur.execute("SELECT count(*) FROM hal_documents WHERE publication_id IS NOT NULL")
    linked = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM hal_documents")
    total = cur.fetchone()[0]
    logger.info(f"  Total : {linked}/{total} hal_documents reliés à une publication")


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_work(cur, staging_row: tuple, max_authors: int = 200) -> bool:
    """Traite un document du staging HAL."""
    staging_id, hal_id, doi, raw_data, collection = staging_row
    doc = raw_data

    title = get_title(doc)
    pub_year = doc.get("producedDateY_i")
    if not title or not pub_year:
        logger.warning(f"Skip {hal_id} — titre ou année manquant")
        return False

    nb_authors = len(doc.get("authFullName_s") or [])
    t0 = time.perf_counter()

    # 1. Créer hal_document
    hal_doc_id = insert_hal_document(cur, staging_id, hal_id, doc)
    if not hal_doc_id:
        return False

    # 2. Créer auteurs + authorships
    extract_authors_and_authorships(cur, doc, hal_doc_id, max_authors=max_authors)

    elapsed = time.perf_counter() - t0
    if elapsed > 2.0 or nb_authors > 50:
        logger.info(f"  {hal_id}: {nb_authors} auteurs, {elapsed:.1f}s")

    # 3. Marquer staging comme traité
    cur.execute("UPDATE staging_hal SET processed = TRUE WHERE id = %s", (staging_id,))
    return True


def main():
    parser = argparse.ArgumentParser(description="Migration HAL → tables v2")
    parser.add_argument("--limit", type=int, help="Nombre max de documents à traiter")
    parser.add_argument("--reset", action="store_true",
                        help="Remettre staging_hal.processed = FALSE")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Taille du commit batch (défaut: 500)")
    parser.add_argument("--max-authors", type=int, default=200,
                        help="Seuil d'auteurs au-delà duquel les authorships sont skippés (défaut: 200)")
    parser.add_argument("--fill-authorships", action="store_true",
                        help="Traiter uniquement les hal_documents sans authorships")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        if args.reset:
            cur.execute("UPDATE staging_hal SET processed = FALSE")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        if args.fill_authorships:
            # Mode complémentaire : traiter les hal_documents sans authorships
            logger.info(f"=== Complétion des authorships manquants (seuil: {args.max_authors}) ===")
            cur.execute("""
                SELECT sh.id, sh.halid, sh.doi, sh.raw_data, sh.collection
                FROM hal_documents hd
                JOIN staging_hal sh ON sh.id = hd.staging_id
                LEFT JOIN hal_authorships ha ON ha.hal_document_id = hd.id
                WHERE ha.id IS NULL
                ORDER BY hd.id
            """)
            rows = cur.fetchall()
            logger.info(f"{len(rows)} documents sans authorships")

            filled = 0
            for row in rows:
                staging_id, hal_id, doi, raw_data, collection = row
                doc = raw_data
                nb_authors = len(doc.get("authFullName_s") or [])

                cur.execute("SELECT id FROM hal_documents WHERE halid = %s", (hal_id,))
                hd_row = cur.fetchone()
                if not hd_row:
                    continue

                extract_authors_and_authorships(cur, doc, hd_row[0],
                                                max_authors=args.max_authors)
                filled += 1
                if filled % 10 == 0:
                    conn.commit()
                    logger.info(f"  {filled}/{len(rows)} traités")

            conn.commit()

            # Re-résoudre UCA pour les nouveaux authorships
            resolve_uca_authorships(cur)
            conn.commit()

            logger.info(f"Complétion terminée : {filled} documents traités")
            cur.execute("SELECT COUNT(*) FROM hal_authorships")
            logger.info(f"  hal_authorships total : {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM hal_authorships WHERE is_uca = TRUE")
            logger.info(f"  hal_authorships UCA : {cur.fetchone()[0]}")
            return

        # Reset processed pour re-traiter tout dans les nouvelles tables
        cur.execute("UPDATE staging_hal SET processed = FALSE")
        conn.commit()
        logger.info("Reset staging_hal.processed pour migration complète")

        cur.execute("SELECT COUNT(*) FROM staging_hal WHERE processed = FALSE")
        total = cur.fetchone()[0]
        logger.info(f"=== Migration HAL : {total} documents à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = min(args.limit or total, total)
        logger.info(f"Traitement de {limit} documents (batch: {args.batch_size})")

        cur.execute("""
            SELECT id, halid, doi, raw_data, collection
            FROM staging_hal
            WHERE processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

        processed = 0
        errors = 0
        t_start = time.perf_counter()

        for row in rows:
            try:
                success = process_work(cur, row, max_authors=args.max_authors)
                if success:
                    processed += 1
            except Exception as e:
                conn.rollback()
                errors += 1
                logger.error(f"Erreur sur {row[1]}: {e}")
                continue

            if processed % args.batch_size == 0 and processed > 0:
                conn.commit()
                elapsed = time.perf_counter() - t_start
                rate = processed / elapsed if elapsed > 0 else 0
                logger.info(f"  {processed}/{limit} ({errors} erreurs) — {rate:.0f} docs/s")

        conn.commit()

        # --- Post-traitement en batch ---

        # Résolution UCA
        resolve_uca_authorships(cur)
        conn.commit()

        # Liaison aux publications existantes
        link_to_existing_publications(cur)
        conn.commit()

        # --- Stats finales ---
        elapsed = time.perf_counter() - t_start
        logger.info(f"\n=== Migration HAL terminée ({elapsed:.1f}s) ===")
        logger.info(f"Documents traités : {processed}")
        logger.info(f"Erreurs : {errors}")

        for table in ["hal_documents", "hal_authors", "hal_authorships"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            logger.info(f"  {table} : {cur.fetchone()[0]} enregistrements")

        cur.execute("SELECT COUNT(*) FROM hal_authorships WHERE is_uca = TRUE")
        logger.info(f"  hal_authorships UCA : {cur.fetchone()[0]}")

        cur.execute("SELECT COUNT(*) FROM hal_documents WHERE publication_id IS NOT NULL")
        linked = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM hal_documents")
        total_docs = cur.fetchone()[0]
        logger.info(f"  hal_documents reliés à publications : {linked}/{total_docs}")

    except KeyboardInterrupt:
        conn.commit()
        logger.warning("Interruption — données traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
