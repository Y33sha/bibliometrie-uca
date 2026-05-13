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
- Affiliations purement textuelles et génériques (tutelles), pas de
  structures détaillées → stockées dans ``source_authorships.source_data``
  pour traçabilité, pas d'``addresses`` ni de ``source_authorship_addresses``.
- ``doc_type`` stocké comme ``NULL`` à la normalisation ; le mapping
  taxonomie CrossRef → enum canonique est appliqué plus tard via
  ``_SOURCE_MAPS``.
- ``oa_status`` non dérivé de CrossRef (pas fiable) ; laissé à NULL
  pour que les autres sources arbitrent via ``refresh_from_sources``.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Row

from application.journals import find_or_create_journal
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.pipeline.normalize.crossref import CrossrefNormalizeQueries
from application.ports.pipeline.staging import StagingQueries
from application.publications import find_or_create as find_or_create_publication
from application.publications import refresh_from_sources, try_merge_by_doi
from application.publishers import find_or_create_publisher
from domain.normalize import normalize_text
from domain.persons.identifiers import compact_identifiers, normalize_orcid
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi
from domain.publications.dedup import has_minimal_publication_metadata
from domain.sources.crossref import (
    extract_crossref_meta,
    extract_crossref_pub_year,
    parse_crossref_issns,
    strip_jats_tags,
)

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
    ext: dict[str, Any] = {}
    issns = msg.get("ISSN") or []
    if isinstance(issns, list) and issns:
        ext["issn"] = [s for s in issns if isinstance(s, str)]
    isbns = msg.get("ISBN") or []
    if isinstance(isbns, list) and isbns:
        ext["isbn"] = [s for s in isbns if isinstance(s, str)]
    return ext or None


def get_biblio(msg: dict) -> dict | None:
    """Volume, issue, page, article-number — repris du CrossRef brut."""
    biblio: dict[str, Any] = {}
    for src_key, dest_key in (
        ("volume", "volume"),
        ("issue", "issue"),
        ("page", "page"),
        ("article-number", "article_number"),
    ):
        val = msg.get(src_key)
        if isinstance(val, str) and val.strip():
            biblio[dest_key] = val.strip()
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


def process_authors(
    conn: Connection,
    queries: CrossrefNormalizeQueries,
    msg: dict,
    doi: str,
    source_publication_id: int,
) -> None:
    """Crée les ``source_authorships`` pour la publi.

    L'ORCID (seul identifiant exploitable côté CrossRef) vit sur
    `source_authorships.person_identifiers`. Les affiliations brutes
    (génériques tutelle) sont stockées sur `source_data`.
    """
    queries.clear_source_authorships_for_publication(conn, source_publication_id)

    authors = msg.get("author") or []
    if not isinstance(authors, list):
        return

    for position, author in enumerate(authors):
        if not isinstance(author, dict):
            continue

        full_name = _author_full_name(author)
        if not full_name:
            continue

        orcid = normalize_orcid(author.get("ORCID"))
        ids = compact_identifiers(orcid=orcid)

        affiliations = _author_affiliation_strings(author)
        sd: dict[str, Any] = {}
        if affiliations:
            sd["affiliations"] = affiliations
        if author.get("sequence"):
            sd["sequence"] = author["sequence"]

        queries.upsert_crossref_source_authorship(
            conn,
            source_publication_id=source_publication_id,
            author_position=position,
            raw_author_name=full_name,
            source_data=sd if sd else None,
            person_identifiers=ids if ids else None,
        )


# =============================================================
# PUBLICATION (rattachement à la table de vérité)
# =============================================================


def find_publication(
    msg: dict,
    journal_id: int | None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche la publi canonique pour un record CrossRef, sans la créer.

    Le matching est en pratique presque toujours par DOI (CrossRef = DOI-driven).
    On passe ``doc_type='other'`` à ``find_or_create`` (le mapping
    CrossRef → enum canonique est appliqué plus tard) : c'est suffisant
    pour le matching DOI.
    """
    title = get_title(msg)
    pub_year = get_pub_year(msg)
    doi = get_doi(msg)
    if not doi or not has_minimal_publication_metadata(title, pub_year):
        return None
    assert isinstance(title, str) and isinstance(pub_year, int)  # narrowing
    pub_id, _ = find_or_create_publication(
        title=title,
        title_normalized=normalize_text(title),
        pub_year=pub_year,
        doc_type="other",
        doi=doi,
        journal_id=journal_id,
        container_title=get_container_title(msg) if not journal_id else None,
        language=get_language(msg),
        allow_create=False,
        repo=pub_repo,
    )
    return pub_id


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: CrossrefNormalizeQueries,
    logger: logging.Logger,
    staging_row: Row[Any],
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
) -> bool | None:
    staging_id = staging_row.id
    raw = staging_row.raw_data
    if not isinstance(raw, dict) or not raw:
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
        logger.warning(f"CrossRef {doi} sans titre ou année — pas de rattachement possible, skip")
        staging_queries.mark_done(conn, staging_id)
        return None
    assert isinstance(title, str) and isinstance(pub_year, int)  # narrowing

    publisher_id = upsert_publisher(msg, publisher_repo=publisher_repo)
    journal_id = upsert_journal(msg, publisher_id, journal_repo=journal_repo)

    publication_id = queries.get_crossref_publication_id(conn, doi)
    if not publication_id:
        publication_id = find_publication(msg, journal_id, pub_repo=pub_repo)
    if publication_id:
        publication_id = try_merge_by_doi(publication_id, doi, repo=pub_repo)

    external_ids = get_external_ids(msg)
    biblio = get_biblio(msg)
    meta = get_meta(msg)

    source_publication_id = queries.upsert_crossref_source_publication(
        conn,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=None,  # mapping CrossRef → enum canonique appliqué plus tard (cf. docs/chantiers/crossref.md)
        publication_id=publication_id,
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

    process_authors(conn, queries, msg, doi, source_publication_id)

    if publication_id:
        refresh_from_sources(publication_id, repo=pub_repo)

    staging_queries.mark_done(conn, staging_id)
    return True


class CrossrefNormalizer(SourceNormalizer):
    SOURCE = "crossref"
    DEFAULT_BATCH_SIZE = 100
    FETCH_COLUMNS = "id, source_id, doi, raw_data"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: CrossrefNormalizeQueries,
        journal_repo_factory: Callable[[Any], JournalRepository],
        publisher_repo_factory: Callable[[Any], PublisherRepository],
        pub_repo_factory: Callable[[Any], PublicationRepository],
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalRepository | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherRepository | None = None
        self._pub_repo_factory = pub_repo_factory
        self._pub_repo: PublicationRepository | None = None

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
        )
