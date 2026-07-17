"""Normalisation des données ScanR : staging → tables structurées."""

import logging
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from application.pipeline.normalize.base import SourceNormalizer
from application.pipeline.timings import StepTimer
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.source_publications import (
    SourcePublicationQueries,
    SourcePublicationRow,
)
from application.ports.pipeline.normalize.staging import StagingQueries, StagingRow
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.services.journals.core import find_or_create_journal
from application.services.publishers.core import find_or_create_publisher
from domain.persons.identifiers import (
    compact_identifiers,
    mark_shared_identifiers_dubious,
    normalize_orcid,
)
from domain.publications.authorship_roles import map_role
from domain.publications.identifiers import clean_doi
from domain.publications.metadata import has_minimal_publication_metadata
from domain.sources.scanr import (
    derive_scanr_oa_status,
    extract_nnt_from_scanr_id,
    select_leaf_affiliations,
)
from domain.types import JsonValue

# =============================================================
# UTILITAIRES
# =============================================================


def extract_doi(doc: dict) -> str | None:
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "doi":
            return clean_doi(ext.get("id"))
    return None


def get_title(doc: dict) -> str | None:
    title = doc.get("title")
    if isinstance(title, dict):
        return title.get("default")
    return title


def upsert_publisher(doc: dict, *, publisher_repo: PublisherRepository) -> int | None:
    publisher_name = (doc.get("source") or {}).get("publisher")
    if not publisher_name:
        return None
    return find_or_create_publisher(publisher_name, repo=publisher_repo)


def _extract_journal_issns(source: dict) -> tuple[str | None, str | None]:
    """Extrait (issn, eissn) depuis `source.journalIssns` (array ScanR).

    Heuristique : 1er = print/issn, 2e = electronic/eissn. Les éventuelles entrées supplémentaires (alias, ISSN-L, variantes historiques) sont ignorées. Cohérent avec ce qu'on fait pour OpenAlex.
    """
    issns = source.get("journalIssns") or []
    issn = issns[0] if len(issns) >= 1 else None
    eissn = issns[1] if len(issns) >= 2 else None
    return issn, eissn


def upsert_journal(
    doc: dict, publisher_id: int | None, *, journal_repo: JournalRepository
) -> int | None:
    source = doc.get("source") or {}
    title = source.get("title")
    if not title:
        return None
    issn, eissn = _extract_journal_issns(source)
    return find_or_create_journal(
        title,
        issn=issn,
        eissn=eissn,
        publisher_id=publisher_id,
        repo=journal_repo,
    )


def extract_pub_metadata(doc: dict, journal_id: int | None, scanr_id: str | None = None) -> dict:
    """Extrait les métadonnées de publication d'un document ScanR.

    Retourne un dict utilisable par `insert_scanr_document`. Toutes les valeurs sont brutes — pas de fallback (le brut de `source_publications.doc_type` est nullable text) ni de transformation de cohérence. `language` est posé à `None` : l'API ScanR ne l'expose pas.
    """
    title = get_title(doc)
    container_title = None
    if not journal_id:
        source = doc.get("source") or {}
        container_title = source.get("title")
    return dict(
        title=title,
        pub_year=doc.get("year"),
        doc_type=doc.get("type"),
        doi=extract_doi(doc),
        nnt=extract_nnt_from_scanr_id(scanr_id),
        oa_status=derive_scanr_oa_status(doc.get("isOa"), doc.get("oaEvidence")),
        journal_id=journal_id,
        container_title=container_title,
        language=None,
    )


# =============================================================
# SOURCE DOCUMENTS (SCANR)
# =============================================================


def insert_scanr_document(
    conn: Connection,
    queries: SourcePublicationQueries,
    doc: dict,
    staging_id: int,
    scanr_id: str,
    pub_meta: dict,
) -> int:
    """Crée/retrouve l'entrée source_publications pour ScanR.

    Les métadonnées canoniques (doi, title, pub_year, doc_type, nnt, journal_id, oa_status, language, container_title) viennent toutes de `pub_meta`, construit en amont par `extract_pub_metadata`. `doc` ne sert ici que pour les champs propres à ScanR (hal_id, pmid, abstract, biblio, keywords, topics, urls).
    """
    ext: dict[str, JsonValue] = {}
    if nnt := pub_meta["nnt"]:
        ext["nnt"] = nnt
    # hal_id et related_dois multivalués : un document ScanR peut référencer plusieurs dépôts HAL et plusieurs DOI (preprint/dépôt/édition).
    hal_ids: list[str] = []
    dois: list[str] = []
    for eid in doc.get("externalIds") or []:
        if not (isinstance(eid, dict) and eid.get("type") and eid.get("id")):
            continue
        etype = eid["type"].lower()
        if etype == "hal" and eid["id"] not in hal_ids:
            hal_ids.append(eid["id"])
        elif etype == "pmid":
            ext["pmid"] = eid["id"]
        elif etype == "doi" and (doi := clean_doi(eid["id"])) and doi not in dois:
            dois.append(doi)
    if hal_ids:
        ext["hal_id"] = hal_ids
    # related_dois = DOI secondaires (autres que le primaire, qui vit sur `doi`).
    # Le doiUrl ScanR est toujours redondant avec un externalIds type=doi.
    if related_dois := [d for d in dois if d != pub_meta["doi"]]:
        ext["related_dois"] = related_dois
    external_ids = ext if ext else None

    summary = doc.get("summary") or {}
    abstract = summary.get("default")

    kw_raw = doc.get("keywords") or {}
    kw_val = kw_raw.get("default")
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

    # Publisher + journal bruts (traçabilité du nom tel que vu par ScanR, en parallèle des publishers/journals créés via find_or_create_*).
    source = doc.get("source") or {}
    biblio: dict[str, JsonValue] = {}
    if publisher_raw := source.get("publisher"):
        biblio["publisher"] = publisher_raw
    journal_obj: dict[str, str] = {}
    if jt := source.get("title"):
        journal_obj["title"] = jt
    jissn, jeissn = _extract_journal_issns(source)
    if jissn:
        journal_obj["issn"] = jissn
    if jeissn:
        journal_obj["eissn"] = jeissn
    if journal_obj:
        biblio["journal"] = journal_obj
    biblio_json = biblio if biblio else None

    return queries.upsert_source_publication(
        conn,
        SourcePublicationRow(
            source="scanr",
            source_id=scanr_id,
            staging_id=staging_id,
            doi=pub_meta["doi"],
            external_ids=external_ids,
            title=pub_meta["title"] or "",
            pub_year=pub_meta["pub_year"],
            doc_type=pub_meta["doc_type"],
            journal_id=pub_meta["journal_id"],
            container_title=pub_meta["container_title"],
            language=pub_meta["language"],
            biblio=biblio_json,
            abstract=abstract,
            keywords=keywords,
            topics=topics,
            oa_status=pub_meta["oa_status"],
            urls=urls or None,
            cited_by_count=cited_by_count,
        ),
    )


# =============================================================
# SCANR AUTHORSHIPS
# =============================================================


def build_scanr_author_records(doc: dict) -> list[AuthorRecord]:
    """Parse les auteurs d'un document ScanR en `AuthorRecord` (sans I/O).

    - identifiants `orcid`/`idref` (sous `denormalized`) ;
    - `roles` via `map_role('scanr', role)` ;
    - affiliations feuilles → adresses, avec `detected_countries` en `countries` (pays d'autorité détectés dans le texte de l'affiliation).
    """
    authors = doc.get("authors") or []
    # Identifiant (orcid/idref) partagé entre ≥2 signatures du doc → `_dubious`.
    ids_by_position = mark_shared_identifiers_dubious(
        [
            compact_identifiers(
                orcid=normalize_orcid((a.get("denormalized") or {}).get("orcid")),
                idref=(a.get("denormalized") or {}).get("idref"),
            )
            for a in authors
        ]
    )

    records: list[AuthorRecord] = []
    for position, author_data in enumerate(authors):
        author_full_name = author_data.get("fullName")
        if not author_full_name:
            continue

        ids = ids_by_position[position]
        roles, _ = map_role("scanr", author_data.get("role"))

        addr_parts: list[str] = []
        detected_countries: set[str] = set()
        for aff in select_leaf_affiliations(author_data.get("affiliations") or []):
            name = (aff.get("name") or "").strip()
            if name:
                addr_parts.append(name)
            detected_countries.update(aff.get("detected_countries") or [])
        countries = sorted(detected_countries) or None

        records.append(
            AuthorRecord(
                position=position,
                raw_name=author_full_name,
                roles=roles or None,
                person_identifiers=ids if ids else None,
                addresses=[AddressRecord(text=part, countries=countries) for part in addr_parts],
            )
        )
    return records


def process_authorships(
    conn: Connection,
    authorship_queries: AuthorshipsBatchQueries,
    doc: dict,
    source_publication_id: int,
) -> None:
    """Parse les auteurs ScanR puis écrit les authorships en batch."""
    records = build_scanr_author_records(doc)
    write_source_authorships(conn, authorship_queries, "scanr", source_publication_id, records)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: SourcePublicationQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    publication_repo: PublicationRepository,
    staging_queries: StagingQueries,
    authorship_queries: AuthorshipsBatchQueries,
) -> bool:
    staging_id = staging_row.id
    scanr_id = staging_row.source_id
    doc = staging_row.raw_data

    title = get_title(doc)
    pub_year = doc.get("year")
    if not has_minimal_publication_metadata(title, pub_year):
        logger.warning(f"Impossible d'insérer {scanr_id} — titre ou année manquant")
        staging_queries.mark_done(conn, staging_id)
        return False

    t = StepTimer()
    publisher_id = upsert_publisher(doc, publisher_repo=publisher_repo)
    journal_id = upsert_journal(doc, publisher_id, journal_repo=journal_repo)
    t.mark("publisher+journal")

    pub_meta = extract_pub_metadata(doc, journal_id, scanr_id)

    source_publication_id = insert_scanr_document(
        conn, queries, doc, staging_id, scanr_id, pub_meta
    )
    t.mark("scanr_doc")

    process_authorships(conn, authorship_queries, doc, source_publication_id)
    t.mark("authors")

    staging_queries.mark_done(conn, staging_id)
    t.log_if_slow(scanr_id, logger)

    return True


class ScanrNormalizer(SourceNormalizer):
    SOURCE = "scanr"
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: SourcePublicationQueries,
        journal_repo_factory: Callable[[Connection], JournalRepository],
        publisher_repo_factory: Callable[[Connection], PublisherRepository],
        publication_repo_factory: Callable[[Connection], PublicationRepository],
        authorship_queries: AuthorshipsBatchQueries,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalRepository | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherRepository | None = None
        self._publication_repo_factory = publication_repo_factory
        self._publication_repo: PublicationRepository | None = None
        self._authorship_queries = authorship_queries

    def preload_caches(self, conn: Connection) -> None:
        self._journal_repo = self._journal_repo_factory(conn)
        self._publisher_repo = self._publisher_repo_factory(conn)
        self._publication_repo = self._publication_repo_factory(conn)

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        assert (
            self._journal_repo is not None
            and self._publisher_repo is not None
            and self._publication_repo is not None
        )
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            journal_repo=self._journal_repo,
            publisher_repo=self._publisher_repo,
            publication_repo=self._publication_repo,
            staging_queries=self._staging,
            authorship_queries=self._authorship_queries,
        )
