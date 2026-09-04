"""Normalisation des données OpenAlex : staging → tables structurées."""

import logging
from collections.abc import Mapping

from sqlalchemy import Connection

from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from application.pipeline.normalize.bibliographic import BibliographicNormalizer
from application.pipeline.normalize.pub_metadata import PublicationMetadata
from application.pipeline.timings import StepTimer
from application.ports.pipeline.journals import JournalFindOrCreateQueries
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.source_publications import (
    SourcePublicationQueries,
    SourcePublicationRow,
)
from application.ports.pipeline.normalize.staging import StagingQueries, StagingRow
from application.ports.pipeline.publishers import PublisherFindOrCreateQueries
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.journals.core import find_or_create_journal
from application.services.publishers.core import find_or_create_publisher
from domain.journals.journal import OaModel
from domain.persons.identifiers import (
    compact_identifiers,
    mark_shared_identifiers_dubious,
    normalize_orcid,
)
from domain.publications.identifiers import clean_doi, extract_doi_from_url, extract_hal_id_from_url
from domain.sources.openalex import (
    OpenalexLocation,
    extract_external_ids_from_urls,
    extract_nnt_from_location,
    is_theses_fr_location,
    map_openalex_oa_status,
    parse_primary_location,
    short_openalex_id,
    should_skip_publisher_journal,
)
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str

# =============================================================
# UTILITAIRES
# =============================================================


def extract_locations_data(
    work: Mapping[str, JsonValue],
) -> tuple[list[str], dict[str, JsonValue]]:
    """Extrait les URLs et identifiants depuis les locations d'un work OpenAlex.

    Retourne (urls, external_ids) où :
      - urls : liste dédupliquée de landing_page_url et pdf_url
      - external_ids : dict d'identifiants (nnt, pmid, pmcid, arxiv_id scalaires ; hal_id et related_dois **listes**)

    hal_id et related_dois sont collectés depuis les URLs **et** depuis `location.id` (formes OAI-PMH `pmh:oai:HAL:<halid>` et `doi:<doi>`), source structurée présente même quand la landing page est une page éditeur. related_dois contient ici **tous** les DOI des locations ; l'appelant en retire le DOI primaire (top-level) de la publication.
    """
    urls: list[str] = []
    seen: set[str] = set()
    location_ids: list[str] = []
    for entree in as_sequence(work.get("locations")):
        loc = as_mapping(entree)
        for key in ("landing_page_url", "pdf_url"):
            url = as_str(loc.get(key))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        if loc_id := as_str(loc.get("id")):
            location_ids.append(loc_id)

    external_ids: dict[str, JsonValue] = dict(extract_external_ids_from_urls(urls))
    # hal_id et related_dois sont multivalués et apparaissent aussi dans les location.id (absents des URLs quand la landing page est une page éditeur).
    # On balaie URLs + location.id en une passe.
    hal_ids: list[str] = [h for e in as_sequence(external_ids.get("hal_id")) if (h := as_str(e))]
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


def reconstruct_abstract(inverted_index: Mapping[str, JsonValue] | None) -> str | None:
    """Reconstruit le texte de l'abstract depuis l'inverted index OpenAlex.

    Le format est {mot: [positions]} → on reconstitue le texte en ordre.
    """
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, indices in inverted_index.items():
        for brut in as_sequence(indices):
            if (idx := as_int(brut)) is not None:
                positions[idx] = word
    if not positions:
        return None
    return " ".join(positions[k] for k in sorted(positions))


def extract_topics(work: Mapping[str, JsonValue]) -> list[dict[str, JsonValue]] | None:
    """Extrait les topics OpenAlex sous forme de liste simplifiée."""
    topics: list[dict[str, JsonValue]] = []
    for entree in as_sequence(work.get("topics")):
        t = as_mapping(entree)
        topic: dict[str, JsonValue] = {}
        for level in ("domain", "field", "subfield", "topic"):
            obj = as_mapping(t.get(level)) or (t if level == "topic" else {})
            if nom := as_str(obj.get("display_name")):
                topic[level] = nom
        if (score := t.get("score")) is not None:
            topic["score"] = score
        if topic:
            topics.append(topic)
    return topics or None


# =============================================================
# PUBLISHERS & JOURNALS
# =============================================================


def upsert_publisher(
    work: Mapping[str, JsonValue], *, publisher_repo: PublisherFindOrCreateQueries
) -> int | None:
    """Extrait et trouve/crée l'éditeur depuis le work OpenAlex."""
    source = as_mapping(as_mapping(work.get("primary_location")).get("source"))
    publisher_name = as_str(source.get("host_organization_name"))
    if not publisher_name:
        return None
    openalex_id = short_openalex_id(as_str(source.get("host_organization")) or "")
    return find_or_create_publisher(
        publisher_name, openalex_id=openalex_id or None, repo=publisher_repo
    )


def upsert_journal(
    work: Mapping[str, JsonValue],
    publisher_id: int | None,
    *,
    journal_repo: JournalFindOrCreateQueries,
) -> int | None:
    """Extrait et trouve/crée la revue depuis le work OpenAlex."""
    source = as_mapping(as_mapping(work.get("primary_location")).get("source"))
    title = as_str(source.get("display_name"))
    if not title:
        return None

    openalex_id = short_openalex_id(as_str(source.get("id")) or "")
    issn_l = as_str(source.get("issn_l"))
    issn = None
    eissn = None
    for entree in as_sequence(source.get("issn")):
        i = as_str(entree)
        if i and i != issn_l:
            if not issn:
                issn = i
            elif not eissn:
                eissn = i

    source_type = as_str(source.get("type"))
    oa_model: OaModel | None = None
    if source_type == "journal":
        oa_model = OaModel.FULL_OA if source.get("is_oa") else OaModel.SUBSCRIPTION
    elif source_type == "repository":
        oa_model = OaModel.REPOSITORY

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
# PUBLICATIONS
# =============================================================


def extract_pub_metadata(
    work: Mapping[str, JsonValue], journal_id: int | None, primary: OpenalexLocation | None = None
) -> PublicationMetadata:
    """Extrait les métadonnées canoniques d'un work OpenAlex.

    Toutes les valeurs sont brutes — pas de transformation de cohérence. `doc_type` est le `work["type"]` brut OpenAlex (mapping canonique en aval, dans `map_doc_type(source="openalex")`).
    """
    title = as_str(work.get("title")) or as_str(work.get("display_name")) or ""
    if primary is None:
        primary = parse_primary_location(work)
    theses_fr = primary is not None and is_theses_fr_location(primary)
    nnt = extract_nnt_from_location(primary) if theses_fr and primary else None
    oa_info = as_mapping(work.get("open_access"))
    container_title = primary.source_display_name if (primary and not journal_id) else None

    return PublicationMetadata(
        title=title,
        pub_year=as_int(work.get("publication_year")),
        doc_type=as_str(work.get("type")),
        doi=clean_doi(as_str(work.get("doi"))),
        nnt=nnt,
        oa_status=map_openalex_oa_status(as_str(oa_info.get("oa_status"))),
        journal_id=journal_id,
        container_title=container_title,
        language=as_str(work.get("language")),
    )


# =============================================================
# SOURCE DOCUMENTS (OPENALEX)
# =============================================================


def insert_openalex_document(  # noqa: C901
    conn: Connection,
    queries: SourcePublicationQueries,
    work: Mapping[str, JsonValue],
    staging_id: int,
    pub_meta: PublicationMetadata,
    primary: OpenalexLocation | None = None,
) -> int:
    """Crée/retrouve l'entrée source_publications pour OpenAlex.

    Les métadonnées canoniques (doi, title, pub_year, doc_type, nnt,
    journal_id, oa_status, language, container_title) viennent toutes de `pub_meta`, construit en amont par `extract_pub_metadata`. `work` ne sert ici que pour les extras OpenAlex-spécifiques (urls, cited_by_count, is_retracted, biblio, publisher/journal bruts, abstract, keywords, topics, location_ids).
    """
    openalex_id = short_openalex_id(as_str(work.get("id")) or "")
    if primary is None:
        primary = parse_primary_location(work)

    # URLs et identifiants extraits des locations
    urls, external_ids = extract_locations_data(work)
    if nnt := pub_meta.nnt:
        external_ids["nnt"] = nnt
    # related_dois (collecté depuis les locations) = DOI secondaires : on retire
    # le DOI primaire de la publication, qui vit sur la colonne `doi`.
    if related_dois := as_sequence(external_ids.get("related_dois")):
        if remaining := [d for d in related_dois if d != pub_meta.doi]:
            external_ids["related_dois"] = remaining
        else:
            del external_ids["related_dois"]

    cited_by_count = as_int(work.get("cited_by_count"))
    is_retracted = bool(work.get("is_retracted"))

    # Biblio (volume, issue, pages)
    raw_biblio = as_mapping(work.get("biblio"))
    biblio: dict[str, JsonValue] = {
        k: raw_biblio[k]
        for k in ("volume", "issue", "first_page", "last_page")
        if raw_biblio.get(k)
    }

    # Publisher + journal bruts (traçabilité du nom tel que vu par OpenAlex, en parallèle des publishers/journals créés via find_or_create_*).
    # Ignoré pour les primary locations qui ne représentent pas un éditeur (HAL, theses.fr, Zenodo, etc.) — même critère que la création.
    if not should_skip_publisher_journal(primary):
        source = as_mapping(as_mapping(work.get("primary_location")).get("source"))
        if publisher_raw := as_str(source.get("host_organization_name")):
            biblio["publisher"] = publisher_raw
        journal_obj: dict[str, str] = {}
        if jt := as_str(source.get("display_name")):
            journal_obj["title"] = jt
        issn_l = as_str(source.get("issn_l"))
        journal_issn = None
        journal_eissn = None
        for entree in as_sequence(source.get("issn")):
            i = as_str(entree)
            if not i or i == issn_l:
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
        if journal_oa_id := short_openalex_id(as_str(source.get("id")) or ""):
            journal_obj["openalex_id"] = journal_oa_id
        if journal_obj:
            biblio["journal"] = journal_obj

    biblio_json = biblio if biblio else None

    # Abstract, keywords, topics
    abstract = reconstruct_abstract(as_mapping(work.get("abstract_inverted_index")))
    mots = [
        as_str(as_mapping(k).get("keyword")) or as_str(k) for k in as_sequence(work.get("keywords"))
    ]
    keywords = [m for m in mots if m] or None
    topics = extract_topics(work)
    topics_json = topics if topics else None

    return queries.upsert_source_publication(
        conn,
        SourcePublicationRow(
            source="openalex",
            source_id=openalex_id,
            staging_id=staging_id,
            doi=pub_meta.doi,
            external_ids=external_ids or None,
            title=pub_meta.title or "",
            pub_year=pub_meta.pub_year,
            doc_type=pub_meta.doc_type,
            journal_id=pub_meta.journal_id,
            container_title=pub_meta.container_title,
            language=pub_meta.language,
            biblio=biblio_json,
            abstract=abstract,
            keywords=keywords,
            topics=topics_json,
            oa_status=pub_meta.oa_status,
            urls=urls or None,
            cited_by_count=cited_by_count,
            is_retracted=is_retracted,
        ),
    )


# =============================================================
# OPENALEX AUTHORS — identifiants sur source_authorships
# =============================================================
# Les entités auteurs OpenAlex sont algorithmiques et non fiables, on garde uniquement l'ORCID quand présent, sur l'identité de la signature (author_identifying_keys.person_identifiers).


def _extract_openalex_orcid(authorship: Mapping[str, JsonValue]) -> str | None:
    """Extrait l'ORCID déposé par l'auteur sur l'authorship (`raw_orcid`).

    OpenAlex porte deux ORCID par authorship, de provenances opposées :

    - `raw_orcid` (niveau authorship) : recopié tel quel de la métadonnée brute du work telle qu'ingérée par OpenAlex depuis sa source amont (Crossref pour l'essentiel des articles à éditeur). C'est l'ORCID déposé par l'auteur à la soumission — fiable au même titre qu'un ORCID Crossref.
    - `author.orcid` (niveau entité auteur OpenAlex) : ORCID de l'entité désambiguïsée par le clustering nom × affiliation d'OpenAlex, régulièrement fautif.

    On retient `raw_orcid` et on ignore `author.orcid`.
    """
    return normalize_orcid(as_str(authorship.get("raw_orcid")))


# =============================================================
# OPENALEX AUTHORSHIPS
# =============================================================


def build_openalex_author_records(work: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Parse les authorships d'un work OpenAlex en `AuthorRecord` (sans I/O).

    - nom brut (`raw_author_name`, fiable contrairement à `author.display_name`) ;
    - ORCID déposé (`raw_orcid`) sur `person_identifiers` ;
    - `country_code` OpenAlex (rattaché à la structure désambiguïsée, algorithmique et faillible) en `suggested_countries` (à valider), jamais en `countries` (autorité) ;
    - `roles=['author']` explicite (OpenAlex ne distingue pas les rôles).
    """
    authorships = [as_mapping(a) for a in as_sequence(work.get("authorships"))]
    # ORCID requalifié `_dubious` s'il est partagé entre ≥2 signatures du work : sur les méga-papers, OpenAlex hérite de crossref l'ORCID du premier auteur recopié sur tous les co-auteurs — invisibilise-le alors au matching.
    ids_by_position = mark_shared_identifiers_dubious(
        [compact_identifiers(orcid=_extract_openalex_orcid(a)) for a in authorships]
    )

    records: list[AuthorRecord] = []
    for position, authorship in enumerate(authorships):
        raw_author_name = as_str(authorship.get("raw_author_name"))
        if not raw_author_name:
            # Sans nom, l'authorship est inexploitable pour le matching personnes.
            continue

        institutions = [as_mapping(i) for i in as_sequence(authorship.get("institutions"))]
        suggested_countries = sorted(
            {pays.lower() for i in institutions if (pays := as_str(i.get("country_code")))}
        )
        raw_strings = [
            texte
            for e in as_sequence(authorship.get("raw_affiliation_strings"))
            if (texte := as_str(e))
        ]
        addr_parts = raw_strings or [
            nom for i in institutions if (nom := as_str(i.get("display_name")))
        ]

        ids = ids_by_position[position]
        records.append(
            AuthorRecord(
                position=position,
                raw_name=raw_author_name,
                is_corresponding=bool(authorship.get("is_corresponding")),
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
    work: Mapping[str, JsonValue],
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
    queries: SourcePublicationQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    journal_repo: JournalFindOrCreateQueries,
    publisher_repo: PublisherFindOrCreateQueries,
    publication_repo: PublicationRepository,
    staging_queries: StagingQueries,
    authorship_queries: AuthorshipsBatchQueries,
) -> bool | None:
    """Traite un work du staging OpenAlex."""
    staging_id = staging_row.id
    openalex_id = staging_row.source_id
    work = staging_row.raw_data

    t = StepTimer()
    primary = parse_primary_location(work)

    if should_skip_publisher_journal(primary):
        publisher_id = None
        journal_id = None
    else:
        publisher_id = upsert_publisher(work, publisher_repo=publisher_repo)
        journal_id = upsert_journal(work, publisher_id, journal_repo=journal_repo)
    t.mark("publisher+journal")

    pub_meta = extract_pub_metadata(work, journal_id, primary)

    source_publication_id = insert_openalex_document(
        conn, queries, work, staging_id, pub_meta, primary
    )
    t.mark("oa_doc")

    process_authorships(conn, authorship_queries, work, source_publication_id)
    t.mark("authors")

    staging_queries.mark_done(conn, staging_id)
    t.log_if_slow(openalex_id, logger)
    return True


class OpenalexNormalizer(BibliographicNormalizer):
    SOURCE = "openalex"
    DEFAULT_BATCH_SIZE = 500

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        journal_repo, publisher_repo, publication_repo = self._require_repos()
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            journal_repo=journal_repo,
            publisher_repo=publisher_repo,
            publication_repo=publication_repo,
            staging_queries=self._staging,
            authorship_queries=self._authorship_queries,
        )
