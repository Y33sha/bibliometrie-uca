"""Normalisation des données DataCite : staging → tables structurées.

L'orchestrateur (classe ``DataciteNormalizer``) dépend des ports
``StagingQueries`` + ``DataciteNormalizeQueries``. Le point d'entrée CLI est
dans ``interfaces/cli/pipeline/normalize_datacite.py``.

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                     (lien staging ↔ publication, source='datacite')
    source_authorships                      (lien document × auteur, source='datacite')

Particularités DataCite :
- Le staging stocke le nœud JSON:API ``data`` ; les métadonnées sont dans
  ``data.attributes``.
- ``creators`` : nom + ORCID éventuel (``nameIdentifiers`` scheme ORCID) +
  affiliations textuelles. Les creators ``Organizational`` (institutions comme
  auteur) sont ignorés — ce ne sont pas des personnes. Affiliations routées vers
  ``addresses`` via le writer batch partagé, comme HAL / OpenAlex / CrossRef.
- ``doc_type`` : token brut issu de ``types`` (cf.
  ``domain.sources.datacite.extract_datacite_doc_type_token``) ; le mapping vers
  l'enum canonique vit dans ``_SOURCE_MAPS["datacite"]`` et est appliqué au refresh.
- ``relatedIdentifiers`` (type DOI) → ``external_ids.related_dois`` (cross-import
  + relations) et ``meta.related_identifiers`` (avec ``relationType``, pour la
  résolution concept/version et les relations entre publications).
- ``oa_status`` non dérivé de DataCite ; laissé à NULL pour arbitrage aval.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection

from application.journals.core import find_or_create_journal
from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.datacite import DataciteNormalizeQueries
from application.ports.pipeline.staging import StagingQueries, StagingRow
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.publishers.core import find_or_create_publisher
from domain.persons.identifiers import (
    compact_identifiers,
    mark_shared_identifiers_dubious,
    normalize_orcid,
)
from domain.publications.identifiers import clean_doi
from domain.publications.metadata import has_minimal_publication_metadata
from domain.sources.datacite import (
    extract_datacite_doc_type_token,
    extract_datacite_meta,
    extract_datacite_pub_year,
    extract_related_dois,
    get_abstract,
    get_cited_by_count,
    get_container,
    get_keywords,
    get_language,
    get_publisher_name,
    get_title,
)
from domain.types import JsonValue

# =============================================================
# PUBLISHER + JOURNAL
# =============================================================


def upsert_publisher(attributes: dict, *, publisher_repo: PublisherRepository) -> int | None:
    name = get_publisher_name(attributes)
    if not name:
        return None
    return find_or_create_publisher(name, repo=publisher_repo)


def upsert_journal(
    attributes: dict,
    publisher_id: int | None,
    *,
    journal_repo: JournalRepository,
) -> int | None:
    """Crée le journal seulement si le `container` porte un titre (revue, série)."""
    title, issn = get_container(attributes)
    if not title:
        return None
    return find_or_create_journal(
        title,
        issn=issn,
        eissn=None,
        publisher_id=publisher_id,
        repo=journal_repo,
    )


def get_biblio(attributes: dict) -> dict | None:
    """Volume / issue / pages depuis `container` + publisher/journal bruts.

    Trace le nom de l'éditeur et de la revue tels que vus par DataCite, en
    parallèle des publishers/journals créés via `find_or_create_*`.
    """
    biblio: dict[str, JsonValue] = {}
    container = attributes.get("container")
    if isinstance(container, dict):
        for src_key, dest_key in (
            ("volume", "volume"),
            ("issue", "issue"),
            ("firstPage", "first_page"),
            ("lastPage", "last_page"),
        ):
            val = container.get(src_key)
            if isinstance(val, str) and val.strip():
                biblio[dest_key] = val.strip()
    if publisher_raw := get_publisher_name(attributes):
        biblio["publisher"] = publisher_raw
    title, issn = get_container(attributes)
    journal_obj: dict[str, str] = {}
    if title:
        journal_obj["title"] = title
    if issn:
        journal_obj["issn"] = issn
    if journal_obj:
        biblio["journal"] = journal_obj
    return biblio or None


# =============================================================
# AUTEURS
# =============================================================


def _creator_full_name(creator: dict) -> str:
    given = (creator.get("givenName") or "").strip()
    family = (creator.get("familyName") or "").strip()
    if given and family:
        return f"{given} {family}"
    name = (creator.get("name") or "").strip()
    return name or family or given or ""


def _creator_orcid(creator: dict) -> str | None:
    """ORCID depuis `nameIdentifiers` (scheme ORCID ou schemeUri orcid.org)."""
    for identifier in creator.get("nameIdentifiers") or []:
        if not isinstance(identifier, dict):
            continue
        scheme = (identifier.get("nameIdentifierScheme") or "").strip().lower()
        scheme_uri = (identifier.get("schemeUri") or "").lower()
        if scheme == "orcid" or "orcid.org" in scheme_uri:
            orcid = normalize_orcid(identifier.get("nameIdentifier"))
            if orcid:
                return orcid
    return None


def _creator_affiliation_strings(creator: dict) -> list[str]:
    """Affiliations textuelles. `affiliation` est une liste de chaînes ou
    d'objets `{name, affiliationIdentifier, ...}` (ROR non exploité ici)."""
    out: list[str] = []
    for aff in creator.get("affiliation") or []:
        if isinstance(aff, str) and aff.strip():
            out.append(aff.strip())
        elif isinstance(aff, dict):
            name = aff.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


def build_datacite_author_records(attributes: dict) -> list[AuthorRecord]:
    """Parse les `creators` DataCite en `AuthorRecord` (sans I/O).

    Ignore les creators `Organizational` (institutions comme auteur). ORCID sur
    `person_identifiers`, affiliations brutes → adresses (sans pays),
    `roles=['author']` explicite.
    """
    creators = attributes.get("creators") or []
    if not isinstance(creators, list):
        return []

    # ORCID partagé entre ≥2 creators du record → `_dubious`.
    ids_by_position = mark_shared_identifiers_dubious(
        [
            compact_identifiers(orcid=_creator_orcid(c)) if isinstance(c, dict) else None
            for c in creators
        ]
    )

    records: list[AuthorRecord] = []
    for position, creator in enumerate(creators):
        if not isinstance(creator, dict):
            continue
        if creator.get("nameType") == "Organizational":
            continue
        full_name = _creator_full_name(creator)
        if not full_name:
            continue
        ids = ids_by_position[position]
        records.append(
            AuthorRecord(
                position=position,
                raw_name=full_name,
                roles=["author"],
                person_identifiers=ids if ids else None,
                addresses=[
                    AddressRecord(text=aff) for aff in _creator_affiliation_strings(creator)
                ],
            )
        )
    return records


def process_authors(
    conn: Connection,
    authorship_queries: AuthorshipsBatchQueries,
    attributes: dict,
    source_publication_id: int,
) -> None:
    records = build_datacite_author_records(attributes)
    write_source_authorships(conn, authorship_queries, "datacite", source_publication_id, records)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: DataciteNormalizeQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
    authorship_queries: AuthorshipsBatchQueries,
) -> bool | None:
    staging_id = staging_row.id
    raw = staging_row.raw_data
    if not raw:
        # Stub not_found ou payload vide — devrait déjà être processed=TRUE.
        staging_queries.mark_done(conn, staging_id)
        return None

    # Le staging stocke le nœud JSON:API `data` ; les métadonnées sont dans
    # `attributes`.
    attributes = raw.get("attributes")
    if not isinstance(attributes, dict):
        logger.warning(f"DataCite staging {staging_id} sans attributes — skip")
        staging_queries.mark_done(conn, staging_id)
        return None

    doi = clean_doi(attributes.get("doi")) or staging_row.doi
    if not doi:
        logger.warning(f"DataCite staging {staging_id} sans DOI exploitable — skip")
        staging_queries.mark_done(conn, staging_id)
        return None

    title = get_title(attributes)
    pub_year = extract_datacite_pub_year(attributes, max_year=datetime.date.today().year + 1)
    if not has_minimal_publication_metadata(title, pub_year):
        logger.warning(f"DataCite {doi} : titre ou année manquant — ignoré")
        staging_queries.mark_done(conn, staging_id)
        return None
    assert isinstance(title, str) and isinstance(pub_year, int)  # narrowing

    from application.pipeline.timings import StepTimer

    t = StepTimer()
    publisher_id = upsert_publisher(attributes, publisher_repo=publisher_repo)
    journal_id = upsert_journal(attributes, publisher_id, journal_repo=journal_repo)
    t.mark("publisher+journal")

    container_title, _ = get_container(attributes)
    related_dois = extract_related_dois(attributes, doi)
    external_ids: dict[str, Any] = {}
    if related_dois:
        external_ids["related_dois"] = related_dois

    source_publication_id = queries.upsert_datacite_source_publication(
        conn,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=extract_datacite_doc_type_token(attributes),
        publication_id=None,
        staging_id=staging_id,
        external_ids=external_ids or None,
        journal_id=journal_id,
        oa_status=None,
        language=get_language(attributes),
        container_title=container_title if not journal_id else None,
        abstract=get_abstract(attributes),
        keywords=get_keywords(attributes),
        cited_by_count=get_cited_by_count(attributes),
        biblio=get_biblio(attributes),
        meta=extract_datacite_meta(attributes),
    )
    t.mark("datacite_doc")

    process_authors(conn, authorship_queries, attributes, source_publication_id)
    t.mark("authors")

    staging_queries.mark_done(conn, staging_id)
    t.log_if_slow(doi, logger)
    return True


class DataciteNormalizer(SourceNormalizer):
    SOURCE = "datacite"
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: DataciteNormalizeQueries,
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
