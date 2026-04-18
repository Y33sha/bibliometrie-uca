"""
Normalisation des données ScanR : staging → tables structurées.

Usage:
    python normalize_scanr.py              # traiter tous les works non traités
    python normalize_scanr.py --limit 100  # traiter N works (pour test)
    python normalize_scanr.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                        (lien staging ↔ publication, source='scanr')
    source_persons                          (auteurs unifiés, source='scanr')
    source_authorships                      (lien document × auteur, source='scanr', avec affiliations)

La résolution UCA (source_authorships.structure_ids, in_perimeter) se fait en post-traitement
via populate_affiliations.py, pas ici.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import os
import time

from psycopg2.extras import Json, RealDictCursor

from application.journals import find_or_create_journal, find_or_create_publisher
from application.publications import find_or_create as find_or_create_publication
from application.publications import refresh_from_sources, try_merge_by_doi
from domain.authorship_roles import map_role
from domain.normalize import normalize_text
from domain.publication import clean_doi, normalize_nnt
from infrastructure.addresses import link_addresses
from infrastructure.db.connection import get_connection
from infrastructure.db_helpers import mark_staging_done
from infrastructure.log import setup_logger

logger = setup_logger("normalize_scanr", os.path.join(os.path.dirname(__file__), "logs"))


# =============================================================
# MAPPINGS
# =============================================================

# ScanR type → notre enum doc_type


# =============================================================
# UTILITAIRES
# =============================================================


def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI depuis les externalIds."""
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "doi":
            return clean_doi(ext.get("id"))
    return None


def extract_hal_id(doc: dict) -> str | None:
    """Extrait le HAL ID depuis les externalIds."""
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "hal":
            return ext.get("id")
    return None


def get_title(doc: dict) -> str | None:
    """Extrait le titre."""
    title = doc.get("title") or {}
    return title.get("default") or title.get("en") or title.get("fr")


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================


def upsert_publisher(cur, doc: dict) -> int | None:
    """Extrait et trouve/crée l'éditeur depuis les champs ScanR."""
    source = doc.get("source") or {}
    publisher_name = source.get("publisher")
    if not publisher_name:
        return None
    return find_or_create_publisher(cur, publisher_name)


def upsert_journal(cur, doc: dict, publisher_id: int | None) -> int | None:
    """Extrait et trouve/crée le journal depuis les champs ScanR."""
    source = doc.get("source") or {}
    title = source.get("title")
    if not title:
        return None

    issns = source.get("journalIssns") or []
    issn = issns[0] if len(issns) >= 1 else None
    eissn = issns[1] if len(issns) >= 2 else None

    return find_or_create_journal(cur, title, issn=issn, eissn=eissn, publisher_id=publisher_id)


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================


def _extract_nnt_from_scanr_id(scanr_id: str) -> str | None:
    """Extrait le NNT depuis un source_id ScanR (format nnt{NNT})."""
    if scanr_id and scanr_id.lower().startswith("nnt"):
        return normalize_nnt(scanr_id[3:])
    return None


def extract_pub_metadata(doc: dict, journal_id: int | None, scanr_id: str | None = None) -> dict:
    """Extrait les métadonnées de publication d'un document ScanR.

    Retourne un dict utilisable par find_or_create_publication.
    """
    doi = extract_doi(doc)
    title = get_title(doc)
    pub_year = doc.get("year")

    doc_type = doc.get("type") or "other"

    oa_status = "green" if doc.get("isOa") else "closed"

    container_title = None
    if not journal_id:
        source = doc.get("source") or {}
        container_title = source.get("title")

    nnt = _extract_nnt_from_scanr_id(scanr_id) if scanr_id else None

    return dict(
        title=title,
        title_normalized=normalize_text(title) if title else None,
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt,
        oa_status=oa_status,
        journal_id=journal_id,
        container_title=container_title,
    )


def find_publication(
    cur, doc: dict, journal_id: int | None, scanr_id: str | None = None
) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    from domain.doc_types import map_doc_type

    meta = extract_pub_metadata(doc, journal_id, scanr_id)
    if not meta["pub_year"] or not meta["title"]:
        return None
    meta["doc_type"] = map_doc_type(meta["doc_type"], "scanr")
    pub_id, _ = find_or_create_publication(cur, **meta, allow_create=False)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (SCANR)
# =============================================================


def insert_scanr_document(
    cur,
    doc: dict,
    staging_id: int,
    scanr_id: str,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    """Crée/retrouve l'entrée source_publications pour ScanR. Retourne source_publications.id."""
    doi = extract_doi(doc)
    hal_id = extract_hal_id(doc)
    title = get_title(doc) or ""
    pub_year = doc.get("year")
    doc_type = doc.get("type")

    # external_ids : identifiants cross-source (hal, nnt, pmid, etc.)
    ext = {}
    if hal_id:
        ext["hal"] = hal_id
    nnt = _extract_nnt_from_scanr_id(scanr_id)
    if nnt:
        ext["nnt"] = nnt
    for eid in doc.get("externalIds") or []:
        if isinstance(eid, dict) and eid.get("type") and eid.get("id"):
            etype = eid["type"].lower()
            if etype == "pmid":
                ext["pmid"] = eid["id"]
            elif etype == "hal" and not ext.get("hal"):
                ext["hal"] = eid["id"]
    external_ids = Json(ext) if ext else None

    # Abstract
    summary = doc.get("summary") or {}
    abstract = summary.get("default") or summary.get("en") or summary.get("fr")

    # Keywords
    kw_raw = doc.get("keywords") or {}
    kw_val = kw_raw.get("default") or kw_raw.get("en") or kw_raw.get("fr")
    if isinstance(kw_val, list):
        keywords = [str(k).strip() for k in kw_val if k] or None
    elif isinstance(kw_val, str) and kw_val:
        keywords = [k.strip() for k in kw_val.split(",") if k.strip()] or None
    else:
        keywords = None

    # Topics (meme format qu'OpenAlex)
    topics_raw = doc.get("topics")
    topics = Json(topics_raw) if topics_raw else None
    # Fallback : domains ScanR
    if not topics_raw:
        domains = doc.get("domains")
        if domains:
            topics = Json(domains)

    # Citations
    cbc = doc.get("cited_by_counts_by_year") or {}
    cited_by_count = sum(cbc.values()) if cbc else None

    # URLs
    urls = []
    seen = set()
    for field in ("landingPage", "doiUrl", "pdfUrl"):
        u = doc.get(field)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    oa_ev = doc.get("oaEvidence") or {}
    for field in ("landingPageUrl", "url", "pdfUrl"):
        u = oa_ev.get(field)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    # Metadonnees de publication (pour creation differee)
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, topics, cited_by_count, urls)
        VALUES ('scanr', %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doi = COALESCE(source_publications.doi, EXCLUDED.doi),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls)
        RETURNING id
    """,
        (
            scanr_id,
            doi,
            title,
            pub_year,
            doc_type,
            publication_id,
            staging_id,
            external_ids,
            journal_id,
            oa_status,
            language,
            container_title,
            abstract,
            keywords,
            topics,
            cited_by_count,
            urls or None,
        ),
    )
    return cur.fetchone()["id"]


# =============================================================
# SCANR AUTHORS (source_persons, source='scanr')
# =============================================================


def upsert_scanr_author(cur, author: dict) -> int | None:
    """Insère/retrouve un auteur ScanR dans source_persons (source='scanr').
    Déduplique par idref (via source_id). L'idref va dans BOTH source_id et idref."""
    full_name = author.get("fullName")
    if not full_name:
        return None

    # Séparer nom/prénom (heuristique : "Prénom Nom")
    parts = full_name.strip().split()
    if len(parts) >= 2:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
    else:
        first_name = None
        last_name = full_name

    denorm = author.get("denormalized") or {}
    idref = denorm.get("idref")
    orcid = denorm.get("orcid")

    # 1. Par idref (clé fiable)
    #    source_id = COALESCE(idref, 'scanr-{old_id}')
    #    idref va aussi dans la colonne idref de source_persons
    if idref:
        source_id = idref
        cur.execute(
            """
            INSERT INTO source_persons
                (source, source_id, full_name, last_name, first_name, orcid, idref)
            VALUES ('scanr', %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
                full_name = EXCLUDED.full_name,
                idref = COALESCE(source_persons.idref, EXCLUDED.idref)
            RETURNING id
        """,
            (source_id, full_name, last_name, first_name, orcid, idref),
        )
        return cur.fetchone()["id"]

    # 2. Par nom exact (auteurs sans idref)
    cur.execute(
        """
        SELECT id FROM source_persons
        WHERE source = 'scanr'
          AND source_id LIKE 'scanr-%%'
          AND full_name = %s
          AND first_name IS NOT DISTINCT FROM %s
        LIMIT 1
    """,
        (full_name, first_name),
    )
    row = cur.fetchone()
    if row:
        return row["id"]

    # 3. Nouveau sans identifiant — on génère un source_id séquentiel
    cur.execute("SELECT nextval('source_persons_id_seq')")
    next_id = cur.fetchone()["nextval"]
    source_id = f"scanr-{next_id}"
    cur.execute(
        """
        INSERT INTO source_persons
            (id, source, source_id, full_name, last_name, first_name, orcid)
        VALUES (%s, 'scanr', %s, %s, %s, %s, %s)
        RETURNING id
    """,
        (next_id, source_id, full_name, last_name, first_name, orcid),
    )
    return cur.fetchone()["id"]


# =============================================================
# SCANR AUTHORSHIPS
# =============================================================


def process_authors(cur, doc: dict, source_publication_id: int):
    """Traite les auteurs d'un document ScanR."""
    authors = doc.get("authors") or []

    for position, author_data in enumerate(authors):
        source_person_id = upsert_scanr_author(cur, author_data)
        if not source_person_id:
            continue

        raw_role = author_data.get("role")
        roles, _ = map_role("scanr", raw_role)

        # Affiliations par auteur : extraire noms (adresses) et pays
        author_affiliations = author_data.get("affiliations") or []
        addr_parts = []
        detected_countries = []

        for aff in author_affiliations:
            name = (aff.get("name") or "").strip()
            if name:
                addr_parts.append(name)
            for c in aff.get("detected_countries") or []:
                if c not in detected_countries:
                    detected_countries.append(c)

        author_full_name = author_data.get("fullName")

        cur.execute(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position, roles,
                 author_name_normalized, raw_author_name)
            VALUES ('scanr', %s, %s, %s, %s, normalize_name_form(%s), %s)
            ON CONFLICT (source_publication_id, source_person_id) DO UPDATE SET
                author_name_normalized = EXCLUDED.author_name_normalized,
                roles = EXCLUDED.roles,
                raw_author_name = EXCLUDED.raw_author_name
            RETURNING id
        """,
            (
                source_publication_id,
                source_person_id,
                position,
                roles or None,
                author_full_name,
                author_full_name,
            ),
        )
        row = cur.fetchone()
        sa_id = row[0] if isinstance(row, tuple) else row["id"]

        if addr_parts:
            link_addresses(cur, sa_id, addr_parts, countries=detected_countries or None)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(cur, staging_row) -> bool:
    """Traite un work du staging ScanR."""
    staging_id = staging_row["id"]
    scanr_id = staging_row["scanr_id"]
    staging_row["doi"]
    raw_data = staging_row["raw_data"]
    doc = raw_data
    timings = {}

    try:
        title = get_title(doc)
        pub_year = doc.get("year")
        if not title or not pub_year:
            logger.warning(f"Impossible d'insérer {scanr_id} — titre ou année manquant")
            return False

        t0 = time.perf_counter()
        publisher_id = upsert_publisher(cur, doc)
        timings["publisher"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        journal_id = upsert_journal(cur, doc, publisher_id)
        timings["journal"] = time.perf_counter() - t0

        # Métadonnées de publication (stockées sur source_publications)
        pub_meta = extract_pub_metadata(doc, journal_id, scanr_id)

        t0 = time.perf_counter()
        # Chercher une publication existante (sans créer)
        publication_id = None

        # Idempotence : réutiliser le publication_id existant
        cur.execute(
            "SELECT publication_id FROM source_publications WHERE source = 'scanr' AND source_id = %s",
            (scanr_id,),
        )
        existing_doc = cur.fetchone()
        if existing_doc and existing_doc["publication_id"]:
            publication_id = existing_doc["publication_id"]

        # Recherche par DOI/NNT/titre (sans création)
        if not publication_id:
            publication_id = find_publication(cur, doc, journal_id, scanr_id)
        timings["publication"] = time.perf_counter() - t0

        # Enrichir la publication existante si trouvée
        if publication_id:
            # Extraire les champs enrichis
            summary = doc.get("summary") or {}
            summary.get("default") or summary.get("en") or summary.get("fr")
            kw_raw = doc.get("keywords") or {}
            kw_val = kw_raw.get("default") or kw_raw.get("en") or kw_raw.get("fr")
            if isinstance(kw_val, list):
                [str(k).strip() for k in kw_val if k] or None
            elif isinstance(kw_val, str) and kw_val:
                [k.strip() for k in kw_val.split(",") if k.strip()] or None
            else:
                pass
            doc.get("topics") or doc.get("domains")

            publication_id = try_merge_by_doi(cur, publication_id, pub_meta["doi"])

        # Document ScanR (source_publications) — publication_id peut être NULL
        t0 = time.perf_counter()
        source_publication_id = insert_scanr_document(
            cur, doc, staging_id, scanr_id, publication_id, pub_meta
        )
        timings["scanr_doc"] = time.perf_counter() - t0

        # Auteurs et authorships
        t0 = time.perf_counter()
        process_authors(cur, doc, source_publication_id)
        timings["authors"] = time.perf_counter() - t0

        # Recalcul complet des métadonnées depuis toutes les sources
        if publication_id:
            refresh_from_sources(cur, publication_id)

        mark_staging_done(cur, staging_id)

        total = sum(timings.values())
        if total > 0.5:
            breakdown = " | ".join(f"{k}:{v:.3f}s" for k, v in timings.items())
            logger.info(f"  SLOW {scanr_id} ({total:.3f}s) : {breakdown}")

        return True

    except Exception as e:
        import traceback

        logger.error(f"Erreur sur {scanr_id}: {e}\n{traceback.format_exc()}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation ScanR → tables structurées")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    parser.add_argument(
        "--reset", action="store_true", help="Remettre tous les works à processed=FALSE"
    )
    parser.add_argument(
        "--batch-size", type=int, default=100, help="Taille du commit batch (défaut: 100)"
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if args.reset:
            cur.execute("UPDATE staging SET processed = FALSE WHERE source = 'scanr'")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM staging WHERE source = 'scanr' AND processed = FALSE"
        )
        total = cur.fetchone()["cnt"]
        logger.info(f"=== Normalisation ScanR : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

        cur.execute(
            """
            SELECT id, source_id AS scanr_id, doi, raw_data
            FROM staging
            WHERE source = 'scanr' AND processed = FALSE
            ORDER BY id
            LIMIT %s
        """,
            (limit,),
        )

        rows = cur.fetchall()
        processed = 0
        errors = 0

        for row in rows:
            try:
                success = process_work(cur, row)
                if success:
                    processed += 1
            except Exception:
                conn.rollback()
                errors += 1
                continue

            if processed % args.batch_size == 0:
                conn.commit()
                logger.info(f"  {processed}/{limit} traités ({errors} erreurs)")

        conn.commit()

        logger.info("\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Erreurs : {errors}")

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
