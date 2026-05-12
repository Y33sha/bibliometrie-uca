"""
Normalisation des données OpenAlex : staging → tables structurées.

Usage:
    python normalize_openalex.py              # traiter tous les works non traités
    python normalize_openalex.py --limit 100  # traiter N works (pour test)
    python normalize_openalex.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications          (tables de vérité — partagées)
    source_publications                            (lien staging ↔ publication, source='openalex')
    source_persons                              (auteurs unifiés, source='openalex')
    source_authorships                          (lien document × auteur, source='openalex', avec source_struct_ids)
    source_structures                           (structures sources, source='openalex')

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Row

from application.journals import find_or_create_journal
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.address_linker import AddressLinker
from application.ports.normalize_openalex import OpenalexNormalizeQueries
from application.ports.staging import StagingQueries
from application.ports.zenodo_resolver import ZenodoResolver
from application.publications import (
    find_by_doi,
    find_by_nnt,
    refresh_from_sources,
    resolve_doi_conflict,
    try_merge_by_doi,
)
from application.publications import find_or_create as find_or_create_publication
from application.publishers import find_or_create_publisher
from domain.normalize import normalize_text
from domain.persons.identifiers import compact_identifiers, normalize_orcid
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi, extract_hal_id_from_url
from domain.sources.openalex import (
    correct_openalex_doc_type,
    extract_external_ids_from_urls,
    extract_nnt_from_location,
    is_hal_location,
    is_theses_fr_location,
    map_openalex_oa_status,
    parse_primary_location,
    should_skip_publisher_journal,
)
from domain.zenodo import ZenodoResolutionError, is_zenodo_doi

# =============================================================
# MAPPINGS
# =============================================================


# =============================================================
# UTILITAIRES
# =============================================================


def extract_locations_data(work: dict) -> tuple[list[str], dict]:
    """Extrait les URLs et identifiants depuis les locations d'un work OpenAlex.

    Retourne (urls, external_ids) où :
      - urls : liste dédupliquée de landing_page_url et pdf_url
      - external_ids : dict d'identifiants extraits des URLs (hal, nnt, pmid, pmc)
    """
    urls = []
    seen = set()
    for loc in work.get("locations") or []:
        for key in ("landing_page_url", "pdf_url"):
            url = loc.get(key)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls, extract_external_ids_from_urls(urls)


def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruit le texte de l'abstract depuis l'inverted index OpenAlex.

    Le format est {mot: [positions]} → on reconstitue le texte en ordre.
    """
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, indices in inverted_index.items():
        for idx in indices:
            positions[idx] = word
    if not positions:
        return None
    return " ".join(positions[k] for k in sorted(positions))


def extract_topics(work: dict) -> list[dict] | None:
    """Extrait les topics OpenAlex sous forme de liste simplifiée."""
    raw = work.get("topics")
    if not raw:
        return None
    topics = []
    for t in raw:
        topic = {}
        for level in ("domain", "field", "subfield", "topic"):
            obj = t.get(level) or t if level == "topic" else t.get(level)
            if obj and obj.get("display_name"):
                topic[level] = obj["display_name"]
        if t.get("score") is not None:
            topic["score"] = t["score"]
        if topic:
            topics.append(topic)
    return topics or None


def extract_short_id(url: str, prefix: str = "https://openalex.org/") -> str:
    """Extrait l'ID court d'une URL OpenAlex."""
    if url and url.startswith(prefix):
        return url.replace(prefix, "")
    return url or ""


def find_hal_publication_id(
    conn: Connection, queries: OpenalexNormalizeQueries, work: dict
) -> int | None:
    """Si le work OpenAlex pointe vers un document HAL existant, retourne le publication_id."""
    location = work.get("primary_location") or {}
    url = location.get("landing_page_url") or ""
    hal_id = extract_hal_id_from_url(url)
    if not hal_id:
        return None
    return queries.fetch_publication_id_for_hal_source(conn, hal_id)


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================


def upsert_publisher(work: dict, *, publisher_repo: PublisherRepository) -> int | None:
    """Extrait et trouve/crée l'éditeur depuis le work OpenAlex."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    publisher_name = source.get("host_organization_name")
    if not publisher_name:
        return None
    openalex_id = extract_short_id(source.get("host_organization") or "")
    return find_or_create_publisher(
        publisher_name, openalex_id=openalex_id or None, repo=publisher_repo
    )


def upsert_journal(
    work: dict, publisher_id: int | None, *, journal_repo: JournalRepository
) -> int | None:
    """Extrait et trouve/crée la revue depuis le work OpenAlex."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    title = source.get("display_name")
    if not title:
        return None

    openalex_id = extract_short_id(source.get("id") or "")
    issn_l = source.get("issn_l")
    issns = source.get("issn") or []
    issn = None
    eissn = None
    for i in issns:
        if i != issn_l:
            if not issn:
                issn = i
            elif not eissn:
                eissn = i

    source_type = source.get("type")
    oa_model = None
    if source_type == "journal":
        oa_model = "full_oa" if source.get("is_oa", False) else "subscription"
    elif source_type == "repository":
        oa_model = "repository"

    return find_or_create_journal(
        title,
        issn=issn,
        eissn=eissn,
        issnl=issn_l,
        publisher_id=publisher_id,
        openalex_id=openalex_id or None,
        oa_model=oa_model,
        repo=journal_repo,
    )


# =============================================================
# PUBLICATIONS (inchangé — table de vérité)
# =============================================================


def extract_pub_metadata(work: dict, journal_id: int | None) -> dict:
    """Extrait les métadonnées de publication d'un work OpenAlex.

    Retourne un dict utilisable par find_or_create_publication.
    """
    doi = clean_doi(work.get("doi"))
    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")

    raw_type = work.get("type") or "other"
    primary = parse_primary_location(work)
    theses_fr = primary is not None and is_theses_fr_location(primary)
    nnt = extract_nnt_from_location(primary) if theses_fr and primary else None
    doc_type = correct_openalex_doc_type(
        raw_type,
        is_theses_fr=theses_fr,
        landing_page_url=primary.landing_page_url if primary else None,
    )

    oa_info = work.get("open_access") or {}
    oa_status = map_openalex_oa_status(oa_info.get("oa_status"))
    language = work.get("language")

    container_title = primary.source_display_name if (primary and not journal_id) else None

    return dict(
        title=title,
        title_normalized=normalize_text(title),
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt,
        oa_status=oa_status,
        journal_id=journal_id,
        container_title=container_title,
        language=language,
    )


def find_publication(
    work: dict,
    journal_id: int | None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(work, journal_id)
    if not meta["pub_year"] or not meta["title"]:
        return None
    pub_id, _ = find_or_create_publication(**meta, allow_create=False, repo=pub_repo)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (OPENALEX)
# =============================================================


def insert_openalex_document(
    conn: Connection,
    queries: OpenalexNormalizeQueries,
    work: dict,
    staging_id: int,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    """
    Crée/retrouve l'entrée source_publications pour OpenAlex.
    Retourne source_publications.id.
    """
    openalex_id = extract_short_id(work["id"])
    doi = clean_doi(work.get("doi"))
    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")
    doc_type = work.get("type")

    # URLs et identifiants extraits des locations
    urls, location_ids = extract_locations_data(work)

    # NNT depuis la structure du work (prioritaire sur celui extrait des URLs)
    primary = parse_primary_location(work)
    if primary and is_theses_fr_location(primary):
        nnt = extract_nnt_from_location(primary)
        if nnt:
            location_ids["nnt"] = nnt

    # Conserver le DOI original si retiré lors d'un conflit chapitre/ouvrage
    if pub_meta and pub_meta.get("source_doi"):
        location_ids["source_doi"] = pub_meta["source_doi"]

    external_ids = location_ids if location_ids else None
    cited_by_count = work.get("cited_by_count")
    is_retracted = work.get("is_retracted") or False

    # Biblio (volume, issue, pages)
    raw_biblio = work.get("biblio") or {}
    biblio_clean = {
        k: raw_biblio[k]
        for k in ("volume", "issue", "first_page", "last_page")
        if raw_biblio.get(k)
    }
    biblio = biblio_clean if biblio_clean else None

    # Abstract, keywords, topics
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    keywords = work.get("keywords")
    if isinstance(keywords, list):
        keywords = [k.get("keyword") if isinstance(k, dict) else k for k in keywords]
        keywords = [k for k in keywords if k] or None
    else:
        keywords = None
    topics = extract_topics(work)
    topics_json = topics if topics else None

    # Métadonnées de publication (pour création différée)
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    return queries.upsert_openalex_source_publication(
        conn,
        openalex_id=openalex_id,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=doc_type,
        publication_id=publication_id,
        staging_id=staging_id,
        external_ids=external_ids,
        urls=urls or None,
        cited_by_count=cited_by_count,
        journal_id=journal_id,
        oa_status=oa_status,
        language=language,
        container_title=container_title,
        is_retracted=is_retracted,
        biblio=biblio,
        abstract=abstract,
        keywords=keywords,
        topics_json=topics_json,
    )


# =============================================================
# OPENALEX AUTHORS (identifiants normalisés sur source_authorships)
# =============================================================
# Plus d'écriture dans source_persons côté OA depuis le chantier
# source_persons (cf. docs/chantiers/2026-04-28_source-persons.md) : les entités
# auteurs OA sont algorithmiques et non fiables, on garde uniquement
# l'ORCID quand présent, directement sur source_authorships.person_identifiers.


def _extract_openalex_orcid(authorship: dict) -> str | None:
    """Extrait l'ORCID canonique de l'auteur OA (ou None)."""
    return normalize_orcid((authorship.get("author") or {}).get("orcid"))


# =============================================================
# OPENALEX AUTHORSHIPS
# =============================================================


def process_authorships(
    conn: Connection,
    queries: OpenalexNormalizeQueries,
    work: dict,
    source_publication_id: int,
    *,
    address_linker: AddressLinker,
) -> None:
    """
    Traite les authorships d'un work OpenAlex :
    - Crée les liens source_authorships (source='openalex', source_person_id=NULL)
    - Stocke l'ORCID dans `sa.person_identifiers` quand présent
    - Stocke les `openalex_id` natifs des institutions dans
      `sa.source_structures` (TEXT[])

    Plus d'écriture sur `source_persons` ni `source_structures` (cf.
    chantier `DATA_simplify-source-tables`).
    """
    authorships = work.get("authorships") or []

    # Pré-nettoyage : un re-traitement peut changer les auteurs/positions,
    # on repart d'une table blanche pour cette publi.
    queries.clear_source_authorships_for_publication(conn, source_publication_id)

    for position, authorship in enumerate(authorships):
        # Nom brut de l'auteur (fiable, contrairement à author.display_name)
        raw_author_name = authorship.get("raw_author_name")
        if not raw_author_name:
            # Sans nom, l'authorship est inexploitable pour le matching
            # personnes — on skip.
            continue

        # Corresponding author
        is_corresponding = authorship.get("is_corresponding", False)

        # Affiliations brutes
        raw_strings = authorship.get("raw_affiliation_strings") or []
        institutions = authorship.get("institutions") or []

        # Institutions OpenAlex → openalex_id natifs (TEXT[])
        source_structures = [
            extract_short_id(inst["id"]) for inst in institutions if inst.get("id")
        ]

        # Adresses individuelles pour link_addresses
        addr_parts = (
            raw_strings
            if raw_strings
            else [n for n in (i.get("display_name") for i in institutions) if n]
        )

        orcid = _extract_openalex_orcid(authorship)
        ids = compact_identifiers(orcid=orcid)
        identifiers = ids if ids else None

        sa_id = queries.upsert_openalex_source_authorship(
            conn,
            source_publication_id=source_publication_id,
            author_position=position,
            source_structures=source_structures or None,
            raw_author_name=raw_author_name,
            is_corresponding=is_corresponding,
            person_identifiers=identifiers,
        )

        if addr_parts:
            address_linker.link(conn, sa_id, addr_parts)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: OpenalexNormalizeQueries,
    logger: logging.Logger,
    staging_row: Row[Any],
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    zenodo_resolver: ZenodoResolver,
    staging_queries: StagingQueries,
    address_linker: AddressLinker,
) -> bool | None:
    """Traite un work du staging OpenAlex."""
    if isinstance(staging_row, dict):
        staging_id = staging_row["id"]
        openalex_id = staging_row["openalex_id"]
        doi = staging_row["doi"]
        work = staging_row["raw_data"]
    else:
        staging_id, openalex_id, doi, work = staging_row

    try:
        raw_doi = clean_doi(doi)
        if raw_doi and is_zenodo_doi(raw_doi):
            try:
                version_doi = zenodo_resolver.resolve(raw_doi)
            except ZenodoResolutionError as e:
                logger.warning(f"  {openalex_id} Zenodo {raw_doi} : {e} — retenté au prochain run")
                return None
            if version_doi:
                if queries.staging_has_openalex_doi(conn, version_doi):
                    logger.info(
                        f"  {openalex_id} concept DOI Zenodo {raw_doi} -> "
                        f"version {version_doi} deja en staging, skip"
                    )
                    staging_queries.mark_done(conn, staging_id)
                    return None

        primary = parse_primary_location(work)

        if should_skip_publisher_journal(primary):
            publisher_id = None
            journal_id = None
        else:
            publisher_id = upsert_publisher(work, publisher_repo=publisher_repo)
            journal_id = upsert_journal(work, publisher_id, journal_repo=journal_repo)

        pub_meta = extract_pub_metadata(work, journal_id)

        publication_id = None
        if primary and is_hal_location(primary):
            publication_id = find_hal_publication_id(conn, queries, work)
        if not publication_id and primary and is_theses_fr_location(primary):
            nnt = extract_nnt_from_location(primary)
            if nnt:
                existing = find_by_nnt(nnt, repo=pub_repo)
                if existing:
                    publication_id = existing.id

        if not publication_id:
            publication_id = queries.get_openalex_publication_id(conn, openalex_id)

        if not publication_id:
            publication_id = find_publication(work, journal_id, pub_repo=pub_repo)

        if publication_id:
            enrich_doi = pub_meta["doi"]
            if enrich_doi:
                existing_by_doi = find_by_doi(enrich_doi, repo=pub_repo)
                if existing_by_doi and existing_by_doi.id != publication_id:
                    original_doi = enrich_doi
                    enrich_doi, _ = resolve_doi_conflict(
                        enrich_doi,
                        pub_meta["doc_type"],
                        pub_meta["title_normalized"],
                        existing_by_doi,
                        repo=pub_repo,
                    )
                    if enrich_doi != original_doi:
                        pub_meta["source_doi"] = original_doi
            publication_id = try_merge_by_doi(publication_id, enrich_doi, repo=pub_repo)

        source_publication_id = insert_openalex_document(
            conn, queries, work, staging_id, publication_id, pub_meta
        )

        process_authorships(
            conn, queries, work, source_publication_id, address_linker=address_linker
        )

        if publication_id:
            refresh_from_sources(publication_id, repo=pub_repo)

        staging_queries.mark_done(conn, staging_id)
        return True

    except Exception as e:
        logger.error(f"Erreur sur {openalex_id}: {e}")
        raise


class OpenalexNormalizer(SourceNormalizer):
    SOURCE = "openalex"
    DEFAULT_BATCH_SIZE = 500
    FETCH_SUB_BATCH = 50
    FETCH_COLUMNS = "id, source_id AS openalex_id, doi, raw_data"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: OpenalexNormalizeQueries,
        journal_repo_factory: Callable[[Any], JournalRepository],
        publisher_repo_factory: Callable[[Any], PublisherRepository],
        pub_repo_factory: Callable[[Any], PublicationRepository],
        zenodo_resolver: ZenodoResolver,
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
        self._zenodo_resolver = zenodo_resolver
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
            zenodo_resolver=self._zenodo_resolver,
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

    def summary_stats(self, conn: Connection) -> list[str]:
        return [
            f"  {table} (openalex) : {self._queries.count_openalex_table(conn, table)} enregistrements"
            for table in ("source_structures", "source_persons", "source_publications")
        ]
