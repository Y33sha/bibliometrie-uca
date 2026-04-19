"""
Corrige les fusions erronées de publications causées par des DOI partagés
entre chapitres et ouvrages.

Détecte les publications dont les documents sources mélangent chapitre/ouvrage
ou contiennent des chapitres avec des titres différents (DOI = celui de l'ouvrage).

Pour chaque cas :
1. Détache tous les documents sources (publication_id = NULL)
2. Retire le DOI des chapitres qui portent un DOI d'ouvrage
3. Supprime les authorships vérité et la publication
4. Recrée les publications via find_or_create (normalisation)
5. Reconstruit les authorships vérité via build_authorships

Usage:
    python scripts/fix_chapter_doi_merges.py              # exécuter
    python scripts/fix_chapter_doi_merges.py --dry-run    # afficher sans modifier
"""

import argparse
import logging
from typing import Any

from psycopg2.extras import RealDictCursor

from application.publications import find_or_create, update_sources
from domain.normalize import normalize_text
from infrastructure.db.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CHAPTER_TYPES = ("book_chapter", "book-chapter", "chapter", "COUV")
BOOK_TYPES = ("book", "OUV")


def find_bad_merges(cur: Any) -> Any:
    """Trouve les publications avec fusion chapitre/ouvrage ou chapitre/chapitre erronée."""
    cur.execute("""
        WITH pub_docs AS (
            SELECT p.id AS pub_id, p.doi,
                   sd.source AS src, sd.id AS doc_id, sd.doc_type, sd.title,
                   sd.pub_year, sd.doi AS doc_doi
            FROM publications p
            JOIN source_publications sd ON sd.publication_id = p.id
            WHERE p.doi IS NOT NULL
        )
        SELECT pub_id, doi, array_agg(DISTINCT doc_type) AS types
        FROM pub_docs
        WHERE doc_type IN ('book_chapter', 'book-chapter', 'chapter', 'COUV',
                           'book', 'OUV')
        GROUP BY pub_id, doi
        HAVING count(DISTINCT doc_type) > 1
            OR (
                array_agg(DISTINCT doc_type)
                    <@ ARRAY['book_chapter','book-chapter','chapter','COUV']
                AND count(DISTINCT doc_id) > 1
            )
    """)
    return cur.fetchall()


def get_pub_documents(cur: Any, pub_id: Any) -> Any:
    """Récupère tous les documents sources d'une publication."""
    cur.execute(
        """
        SELECT id, source AS src, title, doc_type, pub_year, doi
        FROM source_publications WHERE publication_id = %s
    """,
        (pub_id,),
    )
    docs = []
    for r in cur.fetchall():
        docs.append({**r, "table": "source_publications"})
    return docs


def rebuild_doc(cur: Any, doc: Any) -> Any:
    """Recrée une publication pour un document source détaché."""
    title = doc["title"] or ""
    title_norm = normalize_text(title)
    pub_year = doc["pub_year"]
    doc_type_map = {
        "COUV": "book_chapter",
        "book-chapter": "book_chapter",
        "chapter": "book_chapter",
        "OUV": "book",
        "ART": "article",
        "COMM": "conference_paper",
        "POSTER": "conference_paper",
        "THESE": "thesis",
        "HDR": "thesis",
        "MEM": "thesis",
        "REPORT": "report",
        "DOUV": "book",
        "UNDEFINED": "other",
        "OTHER": "other",
        "LECTURE": "other",
        "IMG": "other",
        "VIDEO": "other",
        "SON": "other",
        "MAP": "other",
        "PATENT": "other",
        "preprint": "preprint",
    }
    doc_type = doc_type_map.get(doc["doc_type"], doc["doc_type"] or "other")
    doi = doc["doi"]

    if not title or not pub_year:
        return None

    pub_id, is_new = find_or_create(
        cur,
        title=title,
        title_normalized=title_norm,
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
    )
    return pub_id


def fix(conn: Any, dry_run: Any = False) -> Any:
    cur = conn.cursor(cursor_factory=RealDictCursor)

    bad = find_bad_merges(cur)
    log.info(f"{len(bad)} publications avec fusion chapitre/ouvrage erronée")

    if not bad:
        return

    for row in bad:
        pub_id = row["pub_id"]
        doi = row["doi"]
        types = row["types"]
        log.info(f"\nPublication {pub_id} — DOI {doi} — types: {types}")

        docs = get_pub_documents(cur, pub_id)
        has_book = any(d["doc_type"] in BOOK_TYPES for d in docs)
        titles = set(normalize_text(d["title"]) for d in docs if d["title"])
        has_diff_titles = len(titles) > 1

        for d in docs:
            is_chapter = d["doc_type"] in CHAPTER_TYPES
            log.info(
                f"  [{d['src']}] {d['table']} #{d['id']} "
                f"type={d['doc_type']} doi={d['doi']} "
                f"titre={d['title'][:60] if d['title'] else '?'}..."
            )

            if dry_run:
                if is_chapter and (has_book or has_diff_titles):
                    log.info("    → retirerait le DOI du chapitre")
                log.info(f"    → détacherait de la publication {pub_id}")
                continue

            # Détacher le document
            cur.execute(f"UPDATE {d['table']} SET publication_id = NULL WHERE id = %s", (d["id"],))

            # Retirer le DOI des chapitres si c'est un DOI d'ouvrage
            # ou si chapitres de titres différents
            if is_chapter and (has_book or has_diff_titles):
                cur.execute(f"UPDATE {d['table']} SET doi = NULL WHERE id = %s", (d["id"],))
                d["doi"] = None

        if dry_run:
            log.info(f"  → supprimerait la publication {pub_id}")
            continue

        # Supprimer les authorships vérité et la publication
        cur.execute("DELETE FROM authorships WHERE publication_id = %s", (pub_id,))
        cur.execute(
            "DELETE FROM distinct_publications WHERE pub_id_a = %s OR pub_id_b = %s",
            (pub_id, pub_id),
        )
        cur.execute("DELETE FROM publications WHERE id = %s", (pub_id,))
        log.info(f"  Publication {pub_id} supprimée")

        # Recréer les publications pour chaque document
        for d in docs:
            new_pub_id = rebuild_doc(cur, d)
            if new_pub_id:
                cur.execute(
                    f"UPDATE {d['table']} SET publication_id = %s WHERE id = %s",
                    (new_pub_id, d["id"]),
                )
                update_sources(cur, new_pub_id)
                log.info(f"  [{d['src']}] #{d['id']} → publication {new_pub_id}")
            else:
                log.warning(f"  [{d['src']}] #{d['id']} — pas de titre/année, ignoré")

    if not dry_run:
        conn.commit()
        log.info("\nTerminé.")
        log.info("Relancer build_authorships.py pour reconstruire les authorships vérité :")
        log.info("  python processing/build_authorships.py")
    else:
        log.info("\n[DRY RUN] Aucune modification.")
        conn.rollback()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Corrige les fusions erronées chapitre/ouvrage par DOI"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    try:
        fix(conn, dry_run=args.dry_run)
    finally:
        conn.close()
