"""
Normalisation des données OpenAlex : staging → tables structurées.

Usage:
    python normalize_openalex.py              # traiter tous les works non traités
    python normalize_openalex.py --limit 100  # traiter N works (pour test)
    python normalize_openalex.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                     (lien staging ↔ publication, source='openalex')
    source_authorships                      (lien document × auteur, source='openalex',
                                             avec `person_identifiers` JSONB)

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import logging
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.openalex import OpenalexNormalizeQueries
from application.ports.pipeline.staging import StagingQueries, StagingRow
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
from domain.publications.identifiers import clean_doi, extract_doi_from_url, extract_hal_id_from_url
from domain.sources.openalex import (
    extract_external_ids_from_urls,
    extract_nnt_from_location,
    is_theses_fr_location,
    map_openalex_oa_status,
    parse_primary_location,
    should_skip_publisher_journal,
)
from domain.types import JsonValue

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
      - external_ids : dict d'identifiants (nnt, pmid, pmcid, arxiv_id scalaires ;
        hal_id et related_dois **listes**)

    hal_id et related_dois sont collectés depuis les URLs **et** depuis
    `location.id` (formes OAI-PMH `pmh:oai:HAL:<halid>` et `doi:<doi>`), source
    structurée présente même quand la landing page est une page éditeur.
    related_dois contient ici **tous** les DOI des locations ; l'appelant en
    retire le DOI primaire (top-level) de la publication.
    """
    urls = []
    seen = set()
    location_ids: list[str] = []
    for loc in work.get("locations") or []:
        for key in ("landing_page_url", "pdf_url"):
            url = loc.get(key)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        if loc_id := loc.get("id"):
            location_ids.append(loc_id)

    external_ids = extract_external_ids_from_urls(urls)
    # hal_id et related_dois sont multivalués et apparaissent aussi dans les
    # location.id (absents des URLs quand la landing page est une page éditeur).
    # On balaie URLs + location.id en une passe.
    hal_ids: list[str] = list(external_ids.get("hal_id") or [])
    related_dois: list[str] = []
    for s in (*urls, *location_ids):
        if (hal_id := extract_hal_id_from_url(s)) and hal_id not in hal_ids:
            hal_ids.append(hal_id)
        if (doi := extract_doi_from_url(s)) and doi not in related_dois:
            related_dois.append(doi)
    if hal_ids:
        external_ids["hal_id"] = hal_ids
    if related_dois:
        external_ids["related_dois"] = related_dois
    return urls, external_ids


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

    Retourne un dict utilisable par ``insert_openalex_document``. Toutes les
    valeurs sont brutes — pas de transformation de cohérence. ``doc_type``
    est le ``work["type"]`` brut OpenAlex (mapping canonique en aval, dans
    ``map_doc_type(source="openalex")``).
    """
    title = work.get("title") or work.get("display_name") or ""
    primary = parse_primary_location(work)
    theses_fr = primary is not None and is_theses_fr_location(primary)
    nnt = extract_nnt_from_location(primary) if theses_fr and primary else None
    oa_info = work.get("open_access") or {}
    container_title = primary.source_display_name if (primary and not journal_id) else None

    return dict(
        title=title,
        pub_year=work.get("publication_year"),
        doc_type=work.get("type"),
        doi=clean_doi(work.get("doi")),
        nnt=nnt,
        oa_status=map_openalex_oa_status(oa_info.get("oa_status")),
        journal_id=journal_id,
        container_title=container_title,
        language=work.get("language"),
    )


# =============================================================
# SOURCE DOCUMENTS (OPENALEX)
# =============================================================


def insert_openalex_document(
    conn: Connection,
    queries: OpenalexNormalizeQueries,
    work: dict,
    staging_id: int,
    publication_id: int | None,
    pub_meta: dict,
) -> int:
    """Crée/retrouve l'entrée source_publications pour OpenAlex.

    Les métadonnées canoniques (doi, title, pub_year, doc_type, nnt,
    journal_id, oa_status, language, container_title) viennent toutes de
    ``pub_meta``, construit en amont par ``extract_pub_metadata``. ``work``
    ne sert ici que pour les extras OpenAlex-spécifiques (urls,
    cited_by_count, is_retracted, biblio, publisher/journal bruts,
    abstract, keywords, topics, location_ids).
    """
    openalex_id = extract_short_id(work["id"])
    primary = parse_primary_location(work)

    # URLs et identifiants extraits des locations
    urls, external_ids = extract_locations_data(work)
    if nnt := pub_meta["nnt"]:
        external_ids["nnt"] = nnt
    # Conserver le DOI original si retiré lors d'un conflit chapitre/ouvrage
    if source_doi := pub_meta.get("source_doi"):
        external_ids["source_doi"] = source_doi
    # related_dois (collecté depuis les locations) = DOI secondaires : on retire
    # le DOI primaire de la publication, qui vit sur la colonne `doi`.
    if related_dois := external_ids.get("related_dois"):
        if remaining := [d for d in related_dois if d != pub_meta["doi"]]:
            external_ids["related_dois"] = remaining
        else:
            del external_ids["related_dois"]

    cited_by_count = work.get("cited_by_count")
    is_retracted = work.get("is_retracted") or False

    # Biblio (volume, issue, pages)
    raw_biblio = work.get("biblio") or {}
    biblio: dict[str, JsonValue] = {
        k: raw_biblio[k]
        for k in ("volume", "issue", "first_page", "last_page")
        if raw_biblio.get(k)
    }

    # Publisher + journal bruts (traçabilité du nom tel que vu par OpenAlex,
    # en parallèle des publishers/journals créés via find_or_create_*).
    # Skip pour les primary locations qui ne représentent pas un éditeur
    # (HAL, theses.fr, Zenodo, etc.) — même critère que la création.
    if not should_skip_publisher_journal(primary):
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        if publisher_raw := source.get("host_organization_name"):
            biblio["publisher"] = publisher_raw
        journal_obj: dict[str, str] = {}
        if jt := source.get("display_name"):
            journal_obj["title"] = jt
        issn_l = source.get("issn_l")
        journal_issn = None
        journal_eissn = None
        for i in source.get("issn") or []:
            if i == issn_l:
                continue
            if not journal_issn:
                journal_issn = i
            elif not journal_eissn:
                journal_eissn = i
        if journal_issn:
            journal_obj["issn"] = journal_issn
        if journal_eissn:
            journal_obj["eissn"] = journal_eissn
        if issn_l:
            journal_obj["issnl"] = issn_l
        if journal_oa_id := extract_short_id(source.get("id") or ""):
            journal_obj["openalex_id"] = journal_oa_id
        if journal_obj:
            biblio["journal"] = journal_obj

    biblio_json = biblio if biblio else None

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

    return queries.upsert_openalex_source_publication(
        conn,
        openalex_id=openalex_id,
        doi=pub_meta["doi"],
        title=pub_meta["title"],
        pub_year=pub_meta["pub_year"],
        doc_type=pub_meta["doc_type"],
        publication_id=publication_id,
        staging_id=staging_id,
        external_ids=external_ids or None,
        urls=urls or None,
        cited_by_count=cited_by_count,
        journal_id=pub_meta["journal_id"],
        oa_status=pub_meta["oa_status"],
        language=pub_meta["language"],
        container_title=pub_meta["container_title"],
        is_retracted=is_retracted,
        biblio=biblio_json,
        abstract=abstract,
        keywords=keywords,
        topics_json=topics_json,
    )


# =============================================================
# OPENALEX AUTHORS — identifiants sur source_authorships
# =============================================================
# Les entités auteurs OA sont algorithmiques et non fiables, on garde
# uniquement l'ORCID quand présent, sur l'identité de la signature
# (author_identifying_keys.person_identifiers).


def _extract_openalex_orcid(authorship: dict) -> str | None:
    """Extrait l'ORCID déposé par l'auteur sur l'authorship (`raw_orcid`).

    OpenAlex porte deux ORCID par authorship, de provenances opposées :

    - ``raw_orcid`` (niveau authorship) : recopié tel quel de la métadonnée
      brute du work telle qu'ingérée par OpenAlex depuis sa source amont
      (Crossref pour l'essentiel des articles à éditeur). C'est l'ORCID
      déposé par l'auteur à la soumission — fiable au même titre qu'un
      ORCID Crossref.
    - ``author.orcid`` (niveau entité auteur OpenAlex) : ORCID de l'entité
      désambiguïsée par le clustering nom × affiliation d'OpenAlex,
      régulièrement fautif.

    On retient ``raw_orcid`` et on ignore ``author.orcid``.
    """
    return normalize_orcid(authorship.get("raw_orcid"))


# =============================================================
# OPENALEX AUTHORSHIPS
# =============================================================


def build_openalex_author_records(work: dict) -> list[AuthorRecord]:
    """Parse les authorships d'un work OpenAlex en `AuthorRecord` (sans I/O).

    - nom brut (`raw_author_name`, fiable contrairement à `author.display_name`) ;
    - ORCID déposé (`raw_orcid`) sur `person_identifiers` ;
    - `country_code` OpenAlex (rattaché à la structure désambiguïsée,
      algorithmique et faillible) en `suggested_countries` (à valider), jamais
      en `countries` (autorité) ;
    - `roles=['author']` explicite (OpenAlex ne distingue pas les rôles ; on
      reproduit l'ancien défaut DB `ARRAY['author']`).
    """
    authorships = work.get("authorships") or []
    # ORCID requalifié `_dubious` s'il est partagé entre ≥2 signatures du work : sur les
    # méga-papers, OpenAlex hérite de crossref l'ORCID du premier auteur recopié sur tous
    # les co-auteurs — invisibilise-le alors au matching.
    ids_by_position = mark_shared_identifiers_dubious(
        [compact_identifiers(orcid=_extract_openalex_orcid(a)) for a in authorships]
    )

    records: list[AuthorRecord] = []
    for position, authorship in enumerate(authorships):
        raw_author_name = authorship.get("raw_author_name")
        if not raw_author_name:
            # Sans nom, l'authorship est inexploitable pour le matching personnes.
            continue

        institutions = authorship.get("institutions") or []
        suggested_countries = sorted(
            {inst["country_code"].lower() for inst in institutions if inst.get("country_code")}
        )
        raw_strings = authorship.get("raw_affiliation_strings") or []
        addr_parts = (
            raw_strings
            if raw_strings
            else [n for n in (i.get("display_name") for i in institutions) if n]
        )

        ids = ids_by_position[position]
        records.append(
            AuthorRecord(
                position=position,
                raw_name=raw_author_name,
                is_corresponding=authorship.get("is_corresponding", False),
                roles=["author"],
                person_identifiers=ids if ids else None,
                addresses=[
                    AddressRecord(text=part, suggested_countries=suggested_countries or None)
                    for part in addr_parts
                ],
            )
        )
    return records


def process_authorships(
    conn: Connection,
    authorship_queries: AuthorshipsBatchQueries,
    work: dict,
    source_publication_id: int,
) -> None:
    """Parse les authorships OpenAlex puis écrit les authorships en batch."""
    records = build_openalex_author_records(work)
    write_source_authorships(conn, authorship_queries, "openalex", source_publication_id, records)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: OpenalexNormalizeQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
    authorship_queries: AuthorshipsBatchQueries,
) -> bool | None:
    """Traite un work du staging OpenAlex."""
    staging_id = staging_row.id
    openalex_id = staging_row.source_id
    work = staging_row.raw_data

    try:
        from application.pipeline.timings import StepTimer

        t = StepTimer()
        primary = parse_primary_location(work)

        if should_skip_publisher_journal(primary):
            publisher_id = None
            journal_id = None
        else:
            publisher_id = upsert_publisher(work, publisher_repo=publisher_repo)
            journal_id = upsert_journal(work, publisher_id, journal_repo=journal_repo)
        t.mark("publisher+journal")

        pub_meta = extract_pub_metadata(work, journal_id)

        source_publication_id = insert_openalex_document(
            conn, queries, work, staging_id, None, pub_meta
        )
        t.mark("oa_doc")

        process_authorships(conn, authorship_queries, work, source_publication_id)
        t.mark("authors")

        staging_queries.mark_done(conn, staging_id)
        t.log_if_slow(openalex_id, logger)
        return True

    except Exception as e:
        logger.error(f"Erreur sur {openalex_id}: {e}")
        raise


class OpenalexNormalizer(SourceNormalizer):
    SOURCE = "openalex"
    DEFAULT_BATCH_SIZE = 500

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: OpenalexNormalizeQueries,
        journal_repo_factory: Callable[[Connection], JournalRepository],
        publisher_repo_factory: Callable[[Connection], PublisherRepository],
        pub_repo_factory: Callable[[Connection], PublicationRepository],
        authorship_queries: AuthorshipsBatchQueries,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalRepository | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherRepository | None = None
        self._pub_repo_factory = pub_repo_factory
        self._pub_repo: PublicationRepository | None = None
        self._authorship_queries = authorship_queries

    def preload_caches(self, conn: Connection) -> None:
        self._journal_repo = self._journal_repo_factory(conn)
        self._publisher_repo = self._publisher_repo_factory(conn)
        self._pub_repo = self._pub_repo_factory(conn)

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
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
            authorship_queries=self._authorship_queries,
        )

    def summary_stats(self, conn: Connection) -> list[str]:
        return [
            f"  source_publications (openalex) : "
            f"{self._queries.count_openalex_table(conn, 'source_publications')} enregistrements"
        ]
