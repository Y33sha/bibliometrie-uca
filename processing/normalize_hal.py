"""
Normalisation des données HAL : staging_hal → tables v2.

Usage:
    python normalize_hal.py              # traiter tous les works non traités
    python normalize_hal.py --limit 100  # traiter N works (pour test)
    python normalize_hal.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    hal_documents                           (lien staging ↔ publication)
    hal_authors                             (auteurs HAL dédupliqués par hal_person_id)
    hal_authorships                         (lien document × auteur, avec hal_struct_ids)

La résolution UCA (hal_authorships.structure_ids, is_uca) se fait en post-traitement
via populate_uca_flags.sql, pas ici. Ce script ne fait que stocker les hal_struct_ids
bruts extraits de authIdHasStructure_fs.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import os
import re
import sys
import time

import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import HAL
from db.connection import get_connection
from utils.doi import clean_doi
from utils.log import setup_logger
from utils.normalize import normalize_text
from services.publications import find_or_create as find_or_create_publication
from services.journals import find_or_create_publisher, find_or_create_journal

# ----- Logging -----
logger = setup_logger("normalize_hal", os.path.join(os.path.dirname(__file__), "logs"))


# =============================================================
# MAPPINGS
# =============================================================

# HAL docType_s → notre enum doc_type
DOCTYPE_MAP = {
    "ART": "article",
    "COMM": "conference_paper",
    "POSTER": "conference_paper",
    "OUV": "book",
    "COUV": "book_chapter",
    "DOUV": "book_chapter",
    "THESE": "thesis",
    "HDR": "thesis",
    "PREPRINT": "preprint",
    "PREPUBLICATION": "preprint",
    "UNDEFINED": "other",
    "OTHER": "other",
    "REPORT": "report",
    "MEM": "thesis",
    "LECTURE": "other",
    "IMG": "other",
    "VIDEO": "other",
    "SON": "other",
    "MAP": "other",
    "SOFTWARE": "other",
    "PATENT": "other",
    "NOTE": "article",
    "BLOG": "other",
}


# =============================================================
# UTILITAIRES
# =============================================================


def as_str(value) -> str | None:
    """Extrait une chaîne depuis un champ HAL qui peut être str, list ou None."""
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value)


def get_title(doc: dict) -> str:
    """Extrait le titre depuis les données HAL."""
    titles = doc.get("title_s")
    if isinstance(titles, list) and titles:
        return titles[0]
    if isinstance(titles, str):
        return titles
    label = doc.get("label_s", "")
    return label


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================

def upsert_publisher(cur, publisher_name: str) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(cur, publisher_name)


def upsert_journal(cur, doc: dict, publisher_id: int | None) -> int | None:
    """Extrait et trouve/crée la revue depuis les champs HAL."""
    title = as_str(doc.get("journalTitle_s"))
    if not title:
        return None
    return find_or_create_journal(
        cur, title,
        issn=as_str(doc.get("journalIssn_s")),
        eissn=as_str(doc.get("journalEissn_s")),
        publisher_id=publisher_id)


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================

def find_or_insert_publication(cur, doc: dict, journal_id: int | None,
                               allow_create: bool = True) -> tuple[int, bool]:
    """Cherche ou crée une publication. Délègue au service publications."""
    doi = clean_doi(as_str(doc.get("doiId_s")))
    title = get_title(doc)
    pub_year = doc.get("producedDateY_i")

    if not pub_year or not title:
        return None, False

    raw_type = doc.get("docType_s", "OTHER")
    doc_type = DOCTYPE_MAP.get(raw_type, "other")

    language_list = doc.get("language_s")
    language = language_list[0] if isinstance(language_list, list) and language_list else None

    oa_status = "green" if doc.get("openAccess_bool") else "closed"

    container_title = None
    if not journal_id:
        container_title = as_str(doc.get("bookTitle_s")) or as_str(doc.get("conferenceTitle_s"))

    return find_or_create_publication(
        cur, title=title, title_normalized=normalize_text(title),
        pub_year=pub_year, doc_type=doc_type, doi=doi,
        oa_status=oa_status, journal_id=journal_id,
        container_title=container_title, language=language,
        allow_create=allow_create)


# =============================================================
# HAL DOCUMENTS (nouveau — remplace publication_sources)
# =============================================================

def insert_hal_document(cur, doc: dict, staging_id: int, hal_id: str,
                        collection: str | None,
                        publication_id: int | None) -> int:
    """
    Crée/retrouve l'entrée hal_documents.
    Le champ collections agrège toutes les collections vues.
    Retourne hal_document.id.
    """
    doi = clean_doi(as_str(doc.get("doiId_s")))
    title = get_title(doc)
    pub_year = doc.get("producedDateY_i")
    doc_type = doc.get("docType_s")

    # Collections : depuis le staging (peut être "COL1,COL2") +
    # collCode_s du raw_data
    collections = set()
    if collection:
        for c in collection.split(","):
            c = c.strip()
            if c:
                collections.add(c)
    coll_codes = doc.get("collCode_s") or []
    if isinstance(coll_codes, list):
        collections.update(coll_codes)

    collections_array = sorted(collections) if collections else None

    cur.execute("""
        INSERT INTO hal_documents
            (halid, doi, title, pub_year, doc_type,
             collections, publication_id, staging_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (halid) DO UPDATE SET
            publication_id = COALESCE(
                hal_documents.publication_id, EXCLUDED.publication_id
            ),
            doi = COALESCE(hal_documents.doi, EXCLUDED.doi),
            doc_type = COALESCE(EXCLUDED.doc_type, hal_documents.doc_type),
            collections = (
                SELECT array_agg(DISTINCT c ORDER BY c)
                FROM unnest(
                    COALESCE(hal_documents.collections, '{}') ||
                    COALESCE(EXCLUDED.collections, '{}')
                ) AS c
            )
        RETURNING id
    """, (hal_id, doi, title, pub_year, doc_type,
          collections_array, publication_id, staging_id))
    return cur.fetchone()[0]


# =============================================================
# HAL AUTHORS (nouveau — remplace upsert dans authors)
# =============================================================

def upsert_hal_author(cur, full_name: str, hal_person_id: int | None,
                      idhal: str | None, hal_form_id: int | None = None,
                      orcid: str | None = None) -> int | None:
    """
    Insère/retrouve un auteur HAL.
    Déduplique par :
      1. hal_person_id (clé unique, auteurs avec compte HAL)
      2. hal_form_id (clé unique partielle, auteurs sans compte HAL)
      3. nom exact (dernier recours)
    Retourne hal_authors.id ou None.
    """
    if not full_name:
        return None

    # Séparer nom/prénom (heuristique HAL : souvent "Prénom Nom")
    parts = full_name.strip().split()
    if len(parts) >= 2:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
    else:
        first_name = None
        last_name = full_name

    # 1. Par hal_person_id (clé fiable) — 0 signifie non identifié
    #    hal_form_id est réservé aux auteurs sans compte HAL → ignoré ici
    if hal_person_id and hal_person_id > 0:
        cur.execute("""
            INSERT INTO hal_authors
                (hal_person_id, full_name, last_name, first_name, idhal, orcid)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (hal_person_id) DO UPDATE SET
                idhal = COALESCE(hal_authors.idhal, EXCLUDED.idhal),
                orcid = COALESCE(hal_authors.orcid, EXCLUDED.orcid),
                full_name = EXCLUDED.full_name,
                updated_at = now()
            RETURNING id
        """, (hal_person_id, full_name, last_name, first_name, idhal, orcid))
        return cur.fetchone()[0]

    # 2. Par hal_form_id (auteurs sans compte HAL mais avec form_id)
    if hal_form_id:
        cur.execute("""
            SELECT id FROM hal_authors
            WHERE hal_form_id = %s
            LIMIT 1
        """, (hal_form_id,))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE hal_authors SET
                    idhal = COALESCE(hal_authors.idhal, %s),
                    orcid = COALESCE(hal_authors.orcid, %s),
                    full_name = %s,
                    updated_at = now()
                WHERE id = %s
            """, (idhal, orcid, full_name, row[0]))
            return row[0]

        # Nouveau avec form_id
        cur.execute("""
            INSERT INTO hal_authors
                (full_name, last_name, first_name, idhal, orcid, hal_form_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (full_name, last_name, first_name, idhal, orcid, hal_form_id))
        return cur.fetchone()[0]

    # 3. Pas de hal_person_id ni form_id → chercher par nom exact
    cur.execute("""
        SELECT id FROM hal_authors
        WHERE hal_person_id IS NULL
          AND hal_form_id IS NULL
          AND full_name = %s
          AND first_name IS NOT DISTINCT FROM %s
        LIMIT 1
    """, (full_name, first_name))
    row = cur.fetchone()
    if row:
        if idhal or orcid:
            cur.execute("""
                UPDATE hal_authors SET
                    idhal = COALESCE(hal_authors.idhal, %s),
                    orcid = COALESCE(hal_authors.orcid, %s),
                    updated_at = now()
                WHERE id = %s
            """, (idhal, orcid, row[0]))
        return row[0]

    # 4. Nouveau sans identifiant
    cur.execute("""
        INSERT INTO hal_authors (full_name, last_name, first_name, idhal, orcid)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (full_name, last_name, first_name, idhal, orcid))
    return cur.fetchone()[0]


# =============================================================
# HAL AUTHORSHIPS (nouveau — remplace publication_authors + resolve)
# =============================================================

def parse_author_structures(doc: dict) -> dict[int, set[int]]:
    """
    Parse authIdHasStructure_fs pour extraire le mapping
    form_id → {hal_struct_ids}.

    Format : "formId-personId_FacetSep_Nom_JoinSep_structId_FacetSep_StructNom"

    On utilise le form_id (et non le person_id) comme clé, car le form_id
    est toujours présent, y compris pour les auteurs sans compte HAL
    (personId = 0).
    """
    entries = doc.get("authIdHasStructure_fs") or []
    form_structs: dict[int, set[int]] = {}

    for entry in entries:
        parts = entry.split("_JoinSep_")
        if len(parts) != 2:
            continue

        # Gauche : "formId-personId_FacetSep_Nom"
        left_parts = parts[0].split("_FacetSep_")
        if not left_parts:
            continue
        form_person = left_parts[0]  # "49236-749496"
        dash_parts = form_person.rsplit("-", 1)
        if len(dash_parts) != 2:
            continue
        try:
            form_id = int(dash_parts[0])
        except ValueError:
            continue

        # Droite : "structId_FacetSep_StructNom"
        right_parts = parts[1].split("_FacetSep_")
        if not right_parts:
            continue
        try:
            struct_id = int(right_parts[0])
        except ValueError:
            continue

        form_structs.setdefault(form_id, set()).add(struct_id)

    return form_structs


def process_authors(cur, doc: dict, hal_document_id: int):
    """
    Traite les auteurs d'un document HAL :
    - Parse les champs alignés pour extraire hal_person_id, idhal et form_id
    - Parse authIdHasStructure_fs pour les affiliations (clé = form_id)
    - Crée/retrouve chaque auteur dans hal_authors
    - Crée les hal_authorships avec hal_struct_ids
    """
    names = doc.get("authFullName_s") or []
    orcids = doc.get("authOrcid_s") or []

    # authFullNameFormIDPersonIDIDHal_fs :
    #   "Nom_FacetSep_formId-personId_FacetSep_idhal" — aligné par position
    # C'est le champ le plus complet : on en extrait form_id, person_id et idhal
    composite = doc.get("authFullNameFormIDPersonIDIDHal_fs") or []
    form_id_by_pos = {}
    hal_person_id_by_pos = {}
    idhal_by_pos = {}

    for pos, entry in enumerate(composite):
        parts = entry.split("_FacetSep_")
        if len(parts) >= 2:
            # parts[1] = "formId-personId"
            dash_parts = parts[1].rsplit("-", 1)
            if len(dash_parts) == 2:
                try:
                    form_id = int(dash_parts[0])
                    form_id_by_pos[pos] = form_id
                except ValueError:
                    pass
                try:
                    pid = int(dash_parts[1])
                    if pid > 0:  # 0 = personne non identifiée par HAL
                        hal_person_id_by_pos[pos] = pid
                except ValueError:
                    pass
        if len(parts) >= 3 and parts[2].strip():
            idhal_by_pos[pos] = parts[2].strip()

    # Fallback : si authFullNameFormIDPersonIDIDHal_fs est absent,
    # on utilise les champs séparés (anciens documents)
    if not composite:
        name_idhal = doc.get("authFullNameIdHal_fs") or []
        for pos, entry in enumerate(name_idhal):
            parts = entry.split("_FacetSep_")
            if len(parts) == 2 and parts[1].strip():
                idhal_by_pos[pos] = parts[1].strip()

        name_id = doc.get("authFullNameId_fs") or []
        for pos, entry in enumerate(name_id):
            parts = entry.split("_FacetSep_")
            if len(parts) == 2 and parts[1].strip():
                try:
                    pid = int(parts[1].strip())
                    if pid > 0:
                        hal_person_id_by_pos[pos] = pid
                except ValueError:
                    pass

    # authIdHasStructure_fs → {form_id: set of hal_struct_ids}
    form_struct_map = parse_author_structures(doc)

    for position, name in enumerate(names):
        idhal = idhal_by_pos.get(position)
        hal_person_id = hal_person_id_by_pos.get(position)
        form_id = form_id_by_pos.get(position)
        orcid = orcids[position] if position < len(orcids) else None
        # authOrcid_s peut contenir des chaînes vides
        if orcid and not orcid.strip():
            orcid = None

        hal_author_id = upsert_hal_author(
            cur, name, hal_person_id, idhal, form_id, orcid=orcid
        )
        if not hal_author_id:
            continue

        # Structures affiliées à cet auteur sur ce document (par form_id)
        hal_struct_ids = None
        if form_id and form_id in form_struct_map:
            hal_struct_ids = sorted(form_struct_map[form_id])

        cur.execute("""
            INSERT INTO hal_authorships
                (hal_document_id, hal_author_id, author_position, hal_struct_ids,
                 author_name_normalized)
            VALUES (%s, %s, %s, %s, normalize_name_form(%s))
            ON CONFLICT (hal_document_id, hal_author_id) DO UPDATE SET
                hal_struct_ids = COALESCE(
                    EXCLUDED.hal_struct_ids,
                    hal_authorships.hal_struct_ids
                ),
                author_name_normalized = EXCLUDED.author_name_normalized
        """, (hal_document_id, hal_author_id, position,
              hal_struct_ids, name))


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_work(cur, staging_row: tuple) -> bool:
    """Traite un work du staging HAL."""
    staging_id, hal_id, doi, raw_data, collection = staging_row
    doc = raw_data
    timings = {}

    try:
        title = get_title(doc)
        pub_year = doc.get("producedDateY_i")
        if not title or not pub_year:
            logger.warning(f"Impossible d'insérer {hal_id} — titre ou année manquant")
            return False

        t0 = time.perf_counter()
        publisher_name = as_str(doc.get("journalPublisher_s")) or as_str(doc.get("publisher_s"))
        publisher_id = upsert_publisher(cur, publisher_name)
        timings["publisher"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        journal_id = upsert_journal(cur, doc, publisher_id)
        timings["journal"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        # Hors périmètre UCA (collection = NULL, vient de fetch_missing_hal.py) :
        # on enrichit les publications existantes mais on n'en crée pas de nouvelles
        publication_id, is_new = find_or_insert_publication(
            cur, doc, journal_id, allow_create=(collection is not None)
        )
        timings["publication"] = time.perf_counter() - t0

        if not publication_id:
            if not collection:
                logger.debug(f"  {hal_id} hors périmètre, pas de publication existante → skip")
                cur.execute(
                    "UPDATE staging_hal SET processed = TRUE WHERE id = %s",
                    (staging_id,)
                )
            else:
                logger.warning(f"Impossible d'insérer {hal_id} — échec insertion publication")
            return False

        # Document HAL (remplace l'ancienne publication_sources)
        t0 = time.perf_counter()
        hal_document_id = insert_hal_document(
            cur, doc, staging_id, hal_id, collection, publication_id
        )
        timings["hal_doc"] = time.perf_counter() - t0

        # Auteurs et authorships (avec hal_struct_ids)
        t0 = time.perf_counter()
        process_authors(cur, doc, hal_document_id)
        timings["authors"] = time.perf_counter() - t0

        cur.execute(
            "UPDATE staging_hal SET processed = TRUE WHERE id = %s",
            (staging_id,)
        )

        total = sum(timings.values())
        if total > 0.5:
            breakdown = " | ".join(f"{k}:{v:.3f}s" for k, v in timings.items())
            logger.info(f"  SLOW {hal_id} ({total:.3f}s) : {breakdown}")

        return True

    except Exception as e:
        logger.error(f"Erreur sur {hal_id}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation HAL → tables v2")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    parser.add_argument("--reset", action="store_true",
                        help="Remettre tous les works à processed=FALSE")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Taille du commit batch (défaut: 500)")
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

        cur.execute("SELECT COUNT(*) FROM staging_hal WHERE processed = FALSE")
        total = cur.fetchone()[0]
        logger.info(f"=== Normalisation HAL : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

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
        skipped_hors_perimetre = 0

        for row in rows:
            try:
                success = process_work(cur, row)
                if success:
                    processed += 1
                elif row[4] is None:  # collection = NULL → hors périmètre skipé
                    skipped_hors_perimetre += 1
            except Exception:
                conn.rollback()
                errors += 1
                continue

            if processed % args.batch_size == 0:
                conn.commit()
                logger.info(
                    f"  {processed}/{limit} traités "
                    f"({errors} erreurs, {skipped_hors_perimetre} hors périmètre)"
                )

        conn.commit()

        # Stats finales
        logger.info(f"\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Hors périmètre (enrichissement seul) : {skipped_hors_perimetre}")
        logger.info(f"Erreurs : {errors}")

        for table in ["publications", "journals", "publishers",
                       "hal_documents", "hal_authors", "hal_authorships"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            logger.info(f"  {table} : {count} enregistrements")

        # Stats de recouvrement (publications dans les deux sources)
        cur.execute("""
            SELECT COUNT(*) FROM publications p
            WHERE EXISTS (SELECT 1 FROM hal_documents hd WHERE hd.publication_id = p.id)
              AND EXISTS (SELECT 1 FROM openalex_documents od WHERE od.publication_id = p.id)
        """)
        overlap = cur.fetchone()[0]
        logger.info(f"\nPublications dans les deux sources : {overlap}")

    except KeyboardInterrupt:
        conn.commit()
        logger.warning("Interruption — données déjà traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
