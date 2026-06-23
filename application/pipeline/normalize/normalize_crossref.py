"""Normalisation des données CrossRef : staging → tables structurées.

L'orchestrateur (classe ``CrossrefNormalizer``) dépend des ports
``StagingQueries`` + ``CrossrefNormalizeQueries``. Le point d'entrée
CLI est dans ``interfaces/cli/pipeline/normalize_crossref.py``.

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                     (lien staging ↔ publication, source='crossref')
    source_authorships                      (lien document × auteur, source='crossref')

L'ORCID éventuel d'un auteur CrossRef vit sur
``source_authorships.person_identifiers`` (pas d'identifiant stable
côté auteur).

Particularités CrossRef :
- Affiliations purement textuelles et génériques (tutelles), sans
  structures détaillées. Elles sont routées vers ``addresses`` /
  ``source_authorship_addresses`` via le writer batch partagé
  ``write_source_authorships`` (comme HAL / OpenAlex / ScanR) : la phase ``affiliations`` peut alors
  poser ``in_perimeter`` sur les SA crossref, qui entrent ainsi dans la
  cascade de matching personnes. Couverture partielle (~29 % des auteurs
  CrossRef portent une affiliation), mais strictement mieux que rien.
- ``doc_type`` stocké tel quel depuis ``msg["type"]`` ; le mapping
  taxonomie CrossRef → enum canonique vit dans
  ``domain.source_publications.doc_types._SOURCE_MAPS["crossref"]`` et est
  appliqué par ``arbitrate_doc_type_with_article_subtype`` au moment
  du refresh. Le cas ``journal-article`` indistinct est arbitré contre
  les sous-types plus précis exposés par HAL/OA (review, conference_paper,
  etc.) — cf. ``ARTICLE_SUBTYPES``.
- ``oa_status`` non dérivé de CrossRef (pas fiable) ; laissé à NULL
  pour que les autres sources arbitrent via ``refresh_from_sources``.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable

from sqlalchemy import Connection

from application.journals import find_or_create_journal
from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.crossref import CrossrefNormalizeQueries
from application.ports.pipeline.staging import StagingQueries, StagingRow
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.publishers import find_or_create_publisher
from domain.persons.identifiers import (
    compact_identifiers,
    mark_shared_identifiers_dubious,
    normalize_orcid,
)
from domain.publications.identifiers import clean_doi
from domain.publications.metadata import has_minimal_publication_metadata
from domain.sources.crossref import (
    extract_crossref_meta,
    extract_crossref_pub_year,
    parse_crossref_issns,
    strip_jats_tags,
)
from domain.types import JsonValue

# =============================================================
# EXTRACTEURS DE CHAMPS
# =============================================================


def get_doi(msg: dict) -> str | None:
    """DOI normalisé en lowercase. CrossRef expose le DOI tel que déposé."""
    return clean_doi(msg.get("DOI"))


def get_title(msg: dict) -> str | None:
    titles = msg.get("title") or []
    if isinstance(titles, list) and titles:
        first = titles[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    if isinstance(titles, str) and titles.strip():
        return titles.strip()
    return None


def get_pub_year(msg: dict) -> int | None:
    return extract_crossref_pub_year(msg, max_year=datetime.date.today().year + 1)


def get_container_title(msg: dict) -> str | None:
    cts = msg.get("container-title") or []
    if isinstance(cts, list) and cts:
        first = cts[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    if isinstance(cts, str) and cts.strip():
        return cts.strip()
    return None


def get_issns(msg: dict) -> tuple[str | None, str | None]:
    return parse_crossref_issns(msg)


def get_publisher_name(msg: dict) -> str | None:
    p = msg.get("publisher")
    if isinstance(p, str) and p.strip():
        return p.strip()
    return None


def get_keywords(msg: dict) -> list[str] | None:
    subjects = msg.get("subject") or []
    if not isinstance(subjects, list):
        return None
    cleaned = [s.strip() for s in subjects if isinstance(s, str) and s.strip()]
    return cleaned or None


def get_abstract(msg: dict) -> str | None:
    abstract = msg.get("abstract")
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    cleaned = strip_jats_tags(abstract).strip()
    return cleaned or None


def get_cited_by_count(msg: dict) -> int | None:
    val = msg.get("is-referenced-by-count")
    return val if isinstance(val, int) else None


def get_language(msg: dict) -> str | None:
    lang = msg.get("language")
    if isinstance(lang, str) and lang.strip():
        return lang.strip().lower()
    return None


def get_external_ids(msg: dict) -> dict | None:
    """Identifiants secondaires (ISSN, ISBN). DOI vit dans la colonne dédiée."""
    ext: dict[str, JsonValue] = {}
    issns = msg.get("ISSN") or []
    if isinstance(issns, list) and issns:
        ext["issn"] = [s for s in issns if isinstance(s, str)]
    isbns = msg.get("ISBN") or []
    if isinstance(isbns, list) and isbns:
        ext["isbn"] = [s for s in isbns if isinstance(s, str)]
    return ext or None


def get_biblio(msg: dict) -> dict | None:
    """Volume, issue, page, article-number + publisher/journal bruts.

    `publisher` et `journal` (object) tracent le nom tel que vu par CrossRef
    en parallèle des publishers/journals créés via `find_or_create_*`.
    """
    biblio: dict[str, JsonValue] = {}
    for src_key, dest_key in (
        ("volume", "volume"),
        ("issue", "issue"),
        ("page", "page"),
        ("article-number", "article_number"),
    ):
        val = msg.get(src_key)
        if isinstance(val, str) and val.strip():
            biblio[dest_key] = val.strip()
    if publisher_raw := get_publisher_name(msg):
        biblio["publisher"] = publisher_raw
    journal_obj: dict[str, str] = {}
    if jt := get_container_title(msg):
        journal_obj["title"] = jt
    issn_val, eissn_val = get_issns(msg)
    if issn_val:
        journal_obj["issn"] = issn_val
    if eissn_val:
        journal_obj["eissn"] = eissn_val
    if journal_obj:
        biblio["journal"] = journal_obj
    return biblio or None


def get_meta(msg: dict) -> dict | None:
    return extract_crossref_meta(msg)


# =============================================================
# PUBLISHER + JOURNAL
# =============================================================


def upsert_publisher(msg: dict, *, publisher_repo: PublisherRepository) -> int | None:
    name = get_publisher_name(msg)
    if not name:
        return None
    return find_or_create_publisher(name, repo=publisher_repo)


def upsert_journal(
    msg: dict,
    publisher_id: int | None,
    *,
    journal_repo: JournalRepository,
) -> int | None:
    """Crée le journal seulement si la publi a un container-title (= revue, série, etc.)."""
    title = get_container_title(msg)
    if not title:
        return None
    issn, eissn = get_issns(msg)
    return find_or_create_journal(
        title,
        issn=issn,
        eissn=eissn,
        publisher_id=publisher_id,
        repo=journal_repo,
    )


# =============================================================
# AUTEURS
# =============================================================


def _author_full_name(author: dict) -> str:
    given = (author.get("given") or "").strip()
    family = (author.get("family") or "").strip()
    if given and family:
        return f"{given} {family}"
    return family or given or ""


def _author_affiliation_strings(author: dict) -> list[str]:
    affs = author.get("affiliation") or []
    out: list[str] = []
    for aff in affs:
        if not isinstance(aff, dict):
            continue
        name = aff.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def build_crossref_author_records(msg: dict) -> list[AuthorRecord]:
    """Parse les auteurs d'un message Crossref en `AuthorRecord` (sans I/O).

    - nom reconstruit via `_author_full_name` ;
    - ORCID (seul identifiant exploitable côté CrossRef) sur `person_identifiers` ;
    - affiliations brutes → adresses (sans pays) — c'est ce qui permet à la phase
      `affiliations` de poser `in_perimeter` sur les SA crossref ;
    - `roles=['author']` explicite (Crossref ne distingue pas les rôles ; on
      reproduit l'ancien défaut DB `ARRAY['author']`).
    """
    authors = msg.get("author") or []
    if not isinstance(authors, list):
        return []

    # ORCID requalifié `_dubious` s'il est partagé entre ≥2 signatures du message :
    # le dépôt crossref des méga-papers (collaborations) recopie souvent l'ORCID du
    # premier auteur sur tous les co-auteurs — invisibilise-le alors au matching.
    ids_by_position = mark_shared_identifiers_dubious(
        [
            compact_identifiers(orcid=normalize_orcid(a.get("ORCID")))
            if isinstance(a, dict)
            else None
            for a in authors
        ]
    )

    records: list[AuthorRecord] = []
    for position, author in enumerate(authors):
        if not isinstance(author, dict):
            continue

        full_name = _author_full_name(author)
        if not full_name:
            continue

        ids = ids_by_position[position]
        records.append(
            AuthorRecord(
                position=position,
                raw_name=full_name,
                roles=["author"],
                person_identifiers=ids if ids else None,
                addresses=[AddressRecord(text=aff) for aff in _author_affiliation_strings(author)],
            )
        )
    return records


def process_authors(
    conn: Connection,
    authorship_queries: AuthorshipsBatchQueries,
    msg: dict,
    source_publication_id: int,
) -> None:
    """Parse les auteurs Crossref puis écrit les authorships en batch."""
    records = build_crossref_author_records(msg)
    write_source_authorships(conn, authorship_queries, "crossref", source_publication_id, records)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: CrossrefNormalizeQueries,
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
        # Stub not_found ou payload vide — devrait déjà être processed=TRUE,
        # par sécurité on marque processed et on passe.
        staging_queries.mark_done(conn, staging_id)
        return None

    msg = raw  # CrossRef stocke directement le 'message'
    doi = get_doi(msg)
    if not doi:
        logger.warning(f"CrossRef staging {staging_id} sans DOI exploitable — skip")
        staging_queries.mark_done(conn, staging_id)
        return None

    title = get_title(msg)
    pub_year = get_pub_year(msg)
    if not has_minimal_publication_metadata(title, pub_year):
        logger.warning(f"CrossRef {doi} : titre ou année manquant — ignoré")
        staging_queries.mark_done(conn, staging_id)
        return None
    assert isinstance(title, str) and isinstance(pub_year, int)  # narrowing

    from application.pipeline.timings import StepTimer

    t = StepTimer()
    publisher_id = upsert_publisher(msg, publisher_repo=publisher_repo)
    journal_id = upsert_journal(msg, publisher_id, journal_repo=journal_repo)
    t.mark("publisher+journal")

    external_ids = get_external_ids(msg)
    biblio = get_biblio(msg)
    meta = get_meta(msg)

    source_publication_id = queries.upsert_crossref_source_publication(
        conn,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=msg.get("type"),
        publication_id=None,
        staging_id=staging_id,
        external_ids=external_ids,
        journal_id=journal_id,
        oa_status=None,
        language=get_language(msg),
        container_title=get_container_title(msg) if not journal_id else None,
        abstract=get_abstract(msg),
        keywords=get_keywords(msg),
        cited_by_count=get_cited_by_count(msg),
        biblio=biblio,
        meta=meta,
    )
    t.mark("crossref_doc")

    process_authors(conn, authorship_queries, msg, source_publication_id)
    t.mark("authors")

    staging_queries.mark_done(conn, staging_id)
    t.log_if_slow(doi, logger)
    return True


class CrossrefNormalizer(SourceNormalizer):
    SOURCE = "crossref"
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: CrossrefNormalizeQueries,
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
