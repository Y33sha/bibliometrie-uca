"""
Normalisation des données ScanR : staging → tables structurées.

L'orchestrateur (classe `ScanrNormalizer`) dépend des ports
`StagingQueries` + `ScanrNormalizeQueries`. Le point d'entrée CLI est
dans `interfaces/cli/pipeline/normalize_scanr.py`.

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                     (lien staging ↔ publication, source='scanr')
    source_persons                          (auteurs unifiés, source='scanr')
    source_authorships                      (lien document × auteur, source='scanr')

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Row

from application.journals import find_or_create_journal
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.address_linker import AddressLinker
from application.ports.normalize_scanr import ScanrNormalizeQueries
from application.ports.staging import StagingQueries
from application.publications import find_or_create as find_or_create_publication
from application.publications import refresh_from_sources, try_merge_by_doi
from application.publishers import find_or_create_publisher
from domain.authorship_roles import map_role
from domain.normalize import normalize_text
from domain.persons.creation import should_create_source_person
from domain.persons.identifiers import compact_identifiers, normalize_orcid
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi
from domain.publications.dedup import has_minimal_publication_metadata
from domain.sources.scanr import (
    derive_scanr_oa_status,
    extract_nnt_from_scanr_id,
    select_leaf_affiliations,
)

# =============================================================
# UTILITAIRES
# =============================================================


def extract_doi(doc: dict) -> str | None:
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "doi":
            return clean_doi(ext.get("id"))
    return None


def extract_hal_id(doc: dict) -> str | None:
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "hal":
            return ext.get("id")
    return None


def get_title(doc: dict) -> str | None:
    title = doc.get("title")
    if isinstance(title, dict):
        return title.get("default") or title.get("en") or title.get("fr")
    return title


def upsert_publisher(doc: dict, *, publisher_repo: PublisherRepository) -> int | None:
    publisher_name = (doc.get("source") or {}).get("publisher")
    if not publisher_name:
        return None
    return find_or_create_publisher(publisher_name, repo=publisher_repo)


def upsert_journal(
    doc: dict, publisher_id: int | None, *, journal_repo: JournalRepository
) -> int | None:
    source = doc.get("source") or {}
    title = source.get("title")
    if not title:
        return None
    issn = source.get("issn")
    eissn = source.get("eissn")
    return find_or_create_journal(
        title,
        issn=issn,
        eissn=eissn,
        publisher_id=publisher_id,
        repo=journal_repo,
    )


def extract_pub_metadata(doc: dict, journal_id: int | None, scanr_id: str | None = None) -> dict:
    doi = extract_doi(doc)
    title = get_title(doc)
    pub_year = doc.get("year")
    doc_type = doc.get("type") or "other"
    oa_status = derive_scanr_oa_status(doc.get("isOa"), doc.get("oaEvidence"))
    container_title = None
    if not journal_id:
        source = doc.get("source") or {}
        container_title = source.get("title")
    nnt = extract_nnt_from_scanr_id(scanr_id)
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
    doc: dict,
    journal_id: int | None,
    scanr_id: str | None = None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    from domain.doc_types import map_doc_type

    meta = extract_pub_metadata(doc, journal_id, scanr_id)
    if not meta["pub_year"] or not meta["title"]:
        return None
    meta["doc_type"] = map_doc_type(meta["doc_type"], "scanr")
    pub_id, _ = find_or_create_publication(**meta, allow_create=False, repo=pub_repo)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (SCANR)
# =============================================================


def insert_scanr_document(
    conn: Connection,
    queries: ScanrNormalizeQueries,
    doc: dict,
    staging_id: int,
    scanr_id: str,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    doi = extract_doi(doc)
    hal_id = extract_hal_id(doc)
    title = get_title(doc) or ""
    pub_year = doc.get("year")
    doc_type = doc.get("type")

    ext: dict[str, Any] = {}
    if hal_id:
        ext["hal"] = hal_id
    nnt = extract_nnt_from_scanr_id(scanr_id)
    if nnt:
        ext["nnt"] = nnt
    for eid in doc.get("externalIds") or []:
        if isinstance(eid, dict) and eid.get("type") and eid.get("id"):
            etype = eid["type"].lower()
            if etype == "pmid":
                ext["pmid"] = eid["id"]
            elif etype == "hal" and not ext.get("hal"):
                ext["hal"] = eid["id"]
    external_ids = ext if ext else None

    summary = doc.get("summary") or {}
    abstract = summary.get("default") or summary.get("en") or summary.get("fr")

    kw_raw = doc.get("keywords") or {}
    kw_val = kw_raw.get("default") or kw_raw.get("en") or kw_raw.get("fr")
    if isinstance(kw_val, list):
        keywords = [str(k).strip() for k in kw_val if k] or None
    elif isinstance(kw_val, str) and kw_val:
        keywords = [k.strip() for k in kw_val.split(",") if k.strip()] or None
    else:
        keywords = None

    topics_raw = doc.get("topics")
    topics = topics_raw if topics_raw else None
    if not topics_raw:
        domains = doc.get("domains")
        if domains:
            topics = domains

    cbc = doc.get("cited_by_counts_by_year") or {}
    cited_by_count = sum(cbc.values()) if cbc else None

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

    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    return queries.upsert_scanr_source_publication(
        conn,
        scanr_id=scanr_id,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=doc_type,
        publication_id=publication_id,
        staging_id=staging_id,
        external_ids=external_ids,
        journal_id=journal_id,
        oa_status=oa_status,
        language=language,
        container_title=container_title,
        abstract=abstract,
        keywords=keywords,
        topics=topics,
        cited_by_count=cited_by_count,
        urls=urls or None,
    )


# =============================================================
# SCANR AUTHORS
# =============================================================


def upsert_scanr_author(
    conn: Connection, queries: ScanrNormalizeQueries, author: dict
) -> int | None:
    """Crée un `source_persons` ScanR uniquement quand un idref est fourni.

    Sans idref, retourne None : la `source_authorships` sera insérée
    avec `source_person_id=NULL` et `identifiers={"orcid": ...}` si
    présent (cf. chantier source_persons).
    """
    full_name = author.get("fullName")
    if not full_name:
        return None

    denorm = author.get("denormalized") or {}
    idref = denorm.get("idref")
    if not should_create_source_person(source="scanr", strong_id_value=idref):
        return None
    assert isinstance(idref, str)  # narrowing : garanti par le check ci-dessus

    orcid = normalize_orcid(denorm.get("orcid"))
    return queries.upsert_scanr_source_person_by_idref(
        conn,
        idref=idref,
        full_name=full_name,
        orcid=orcid,
    )


# =============================================================
# SCANR AUTHORSHIPS
# =============================================================


def process_authors(
    conn: Connection,
    queries: ScanrNormalizeQueries,
    doc: dict,
    source_publication_id: int,
    *,
    address_linker: AddressLinker,
) -> None:
    # Pré-nettoyage : re-traitement → table blanche pour cette publi.
    queries.clear_source_authorships_for_publication(conn, source_publication_id)

    authors = doc.get("authors") or []

    for position, author_data in enumerate(authors):
        author_full_name = author_data.get("fullName")
        if not author_full_name:
            continue

        # Avec idref : crée le source_persons (cas légitime conservé)
        # Sans idref : source_person_id reste NULL (ORCID éventuel sur identifiers)
        source_person_id = upsert_scanr_author(conn, queries, author_data)

        denorm = author_data.get("denormalized") or {}
        ids = compact_identifiers(
            orcid=normalize_orcid(denorm.get("orcid")),
            idref=denorm.get("idref"),
        )
        identifiers = ids if ids else None

        raw_role = author_data.get("role")
        roles, _ = map_role("scanr", raw_role)

        author_affiliations = author_data.get("affiliations") or []
        kept_affiliations = select_leaf_affiliations(author_affiliations)

        addr_parts = []
        detected_countries: set[str] = set()

        for aff in kept_affiliations:
            name = (aff.get("name") or "").strip()
            if name:
                addr_parts.append(name)
            detected_countries.update(aff.get("detected_countries") or [])

        sa_id = queries.upsert_scanr_source_authorship(
            conn,
            source_publication_id=source_publication_id,
            source_person_id=source_person_id,
            author_position=position,
            roles=roles or None,
            raw_author_name=author_full_name,
            identifiers=identifiers,
        )

        if addr_parts:
            address_linker.link(conn, sa_id, addr_parts, countries=list(detected_countries) or None)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: ScanrNormalizeQueries,
    logger: logging.Logger,
    staging_row: Row[Any],
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
    address_linker: AddressLinker,
) -> bool:
    staging_id = staging_row.id
    scanr_id = staging_row.scanr_id
    raw_data = staging_row.raw_data
    doc = raw_data
    timings: dict[str, float] = {}

    try:
        title = get_title(doc)
        pub_year = doc.get("year")
        if not has_minimal_publication_metadata(title, pub_year):
            logger.warning(f"Impossible d'insérer {scanr_id} — titre ou année manquant")
            return False

        t0 = time.perf_counter()
        publisher_id = upsert_publisher(doc, publisher_repo=publisher_repo)
        timings["publisher"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        journal_id = upsert_journal(doc, publisher_id, journal_repo=journal_repo)
        timings["journal"] = time.perf_counter() - t0

        pub_meta = extract_pub_metadata(doc, journal_id, scanr_id)

        t0 = time.perf_counter()
        publication_id = queries.get_scanr_publication_id(conn, scanr_id)
        if not publication_id:
            publication_id = find_publication(doc, journal_id, scanr_id, pub_repo=pub_repo)
        timings["publication"] = time.perf_counter() - t0

        if publication_id:
            publication_id = try_merge_by_doi(publication_id, pub_meta["doi"], repo=pub_repo)

        t0 = time.perf_counter()
        source_publication_id = insert_scanr_document(
            conn, queries, doc, staging_id, scanr_id, publication_id, pub_meta
        )
        timings["scanr_doc"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        process_authors(conn, queries, doc, source_publication_id, address_linker=address_linker)
        timings["authors"] = time.perf_counter() - t0

        if publication_id:
            refresh_from_sources(publication_id, repo=pub_repo)

        staging_queries.mark_done(conn, staging_id)

        total = sum(timings.values())
        if total > 0.5:
            breakdown = " | ".join(f"{k}:{v:.3f}s" for k, v in timings.items())
            logger.info(f"  SLOW {scanr_id} ({total:.3f}s) : {breakdown}")

        return True

    except Exception as e:
        import traceback

        logger.error(f"Erreur sur {scanr_id}: {e}\n{traceback.format_exc()}")
        raise


class ScanrNormalizer(SourceNormalizer):
    SOURCE = "scanr"
    DEFAULT_BATCH_SIZE = 100
    FETCH_COLUMNS = "id, source_id AS scanr_id, doi, raw_data"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: ScanrNormalizeQueries,
        journal_repo_factory: Callable[[Any], JournalRepository],
        publisher_repo_factory: Callable[[Any], PublisherRepository],
        pub_repo_factory: Callable[[Any], PublicationRepository],
        address_linker: AddressLinker,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalRepository | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherRepository | None = None
        self._pub_repo_factory = pub_repo_factory
        self._pub_repo: PublicationRepository | None = None
        self._address_linker = address_linker

    def preload_caches(self, conn: Connection) -> None:
        self._journal_repo = self._journal_repo_factory(conn)
        self._publisher_repo = self._publisher_repo_factory(conn)
        self._pub_repo = self._pub_repo_factory(conn)

    def process_work(self, conn: Connection, row: Row[Any]) -> bool | None:
        assert (
            self._journal_repo is not None
            and self._publisher_repo is not None
            and self._pub_repo is not None
        )
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            journal_repo=self._journal_repo,
            publisher_repo=self._publisher_repo,
            pub_repo=self._pub_repo,
            staging_queries=self._staging,
            address_linker=self._address_linker,
        )

    def cleanup(self) -> None:
        self._address_linker.clear_cache()

    def on_error(self) -> None:
        # Le cache peut contenir des address_id insérés dans la transaction
        # qui vient d'être rollbackée — invalide-le pour éviter les FK
        # violations sur les works suivants.
        self._address_linker.clear_cache()
