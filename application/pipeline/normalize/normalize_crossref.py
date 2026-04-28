"""Normalisation des données CrossRef : staging → tables structurées.

L'orchestrateur (classe ``CrossrefNormalizer``) dépend des ports
``StagingQueries`` + ``CrossrefNormalizeQueries``. Le point d'entrée
CLI est dans ``interfaces/cli/pipeline/normalize_crossref.py``.

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                     (lien staging ↔ publication, source='crossref')
    source_persons                          (auteurs synthétiques DOI:position, source='crossref')
    source_authorships                      (lien document × auteur, source='crossref')

Particularités CrossRef :
- Pas d'identifiant stable côté auteur → ``source_id = '<DOI>:<position>'``
  pour les ``source_persons``, déduplication transverse au pipeline
  ``personnes`` (source-agnostique).
- Affiliations purement textuelles et génériques (tutelles), pas de
  structures détaillées → stockées dans ``source_authorships.source_data``
  pour traçabilité, pas d'``addresses`` ni de ``source_authorship_addresses``.
- ``doc_type`` stocké comme ``NULL`` en phase 1 ; le mapping
  taxonomie CrossRef → enum canonique vit en phase 2 (``_SOURCE_MAPS``).
- ``oa_status`` non dérivé de CrossRef (pas fiable) ; laissé à NULL
  pour que les autres sources arbitrent via ``refresh_from_sources``.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb as Json

from application.journals import find_or_create_journal
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.normalize_crossref import CrossrefNormalizeQueries
from application.ports.staging import StagingQueries
from application.publications import find_or_create as find_or_create_publication
from application.publications import refresh_from_sources, try_merge_by_doi
from application.publishers import find_or_create_publisher
from domain.normalize import normalize_text
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi


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
    """Année de publication, dans l'ordre : issued > published > online > print."""
    for field in ("issued", "published", "published-online", "published-print"):
        d = msg.get(field) or {}
        date_parts = d.get("date-parts") or []
        if date_parts and isinstance(date_parts[0], list) and date_parts[0]:
            try:
                year = int(date_parts[0][0])
                if 1500 <= year <= 9999:
                    return year
            except (TypeError, ValueError):
                continue
    return None


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
    """Retourne (issn print, eissn) si distinguables, sinon (premier ISSN, None)."""
    issn_print: str | None = None
    eissn: str | None = None
    for issn_obj in msg.get("issn-type") or []:
        if not isinstance(issn_obj, dict):
            continue
        t = issn_obj.get("type")
        v = issn_obj.get("value")
        if not isinstance(v, str) or not v.strip():
            continue
        if t == "electronic" and not eissn:
            eissn = v.strip()
        elif t == "print" and not issn_print:
            issn_print = v.strip()
    if issn_print or eissn:
        return issn_print, eissn
    issns = msg.get("ISSN") or []
    if isinstance(issns, list) and issns:
        first = issns[0]
        if isinstance(first, str) and first.strip():
            return first.strip(), None
    return None, None


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


_JATS_TAG_RE = re.compile(r"<[^>]+>")


def get_abstract(msg: dict) -> str | None:
    """CrossRef stocke l'abstract en JATS XML ; on retire les tags."""
    abstract = msg.get("abstract")
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    cleaned = _JATS_TAG_RE.sub("", abstract).strip()
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
    """Champs CrossRef-spécifiques stockés en jsonb (cf. décision actée plan).

    Pour l'instant on stocke license/funder/relation/references_count/
    indexed_timestamp tels quels — la phase 5 (relations) lira
    ``meta->'relation'``.
    """
    meta: dict[str, Any] = {}
    for key in ("license", "funder", "relation"):
        val = msg.get(key)
        if val:
            meta[key] = val
    refs_count = msg.get("references-count")
    if isinstance(refs_count, int) and refs_count > 0:
        meta["references_count"] = refs_count
    indexed = msg.get("indexed") or {}
    if isinstance(indexed, dict):
        ts = indexed.get("timestamp") or indexed.get("date-time")
        if ts:
            meta["indexed"] = ts
    return meta or None


# =============================================================
# PUBLISHER + JOURNAL
# =============================================================


def upsert_publisher(
    cur: Any, msg: dict, *, publisher_repo: PublisherRepository
) -> int | None:
    name = get_publisher_name(msg)
    if not name:
        return None
    return find_or_create_publisher(cur, name, repo=publisher_repo)


def upsert_journal(
    cur: Any,
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
        cur,
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


def _normalize_orcid(raw: str | None) -> str | None:
    """Extrait l'ORCID 16 chars depuis une URL CrossRef (https://orcid.org/...)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    extracted = raw.rstrip("/").split("/")[-1].strip()
    return extracted or None


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
    cur: Any,
    queries: CrossrefNormalizeQueries,
    msg: dict,
    doi: str,
    source_publication_id: int,
) -> None:
    """Crée les ``source_persons`` + ``source_authorships`` pour la publi.

    Stratégie : un ``source_persons`` par paire (publi, position), pas
    de matching transverse côté CrossRef. Le pipeline ``personnes``
    (source-agnostique) consolide ensuite via les formes de noms et
    les ORCIDs.
    """
    queries.clear_source_authorships_for_publication(cur, source_publication_id)

    authors = msg.get("author") or []
    if not isinstance(authors, list):
        return

    for position, author in enumerate(authors):
        if not isinstance(author, dict):
            continue

        full_name = _author_full_name(author)
        if not full_name:
            continue
        family = (author.get("family") or "").strip() or None
        given = (author.get("given") or "").strip() or None
        orcid = _normalize_orcid(author.get("ORCID"))

        source_person_id = queries.insert_crossref_source_person(
            cur,
            doi=doi,
            position=position,
            full_name=full_name,
            last_name=family,
            first_name=given,
            orcid=orcid,
        )

        affiliations = _author_affiliation_strings(author)
        sd: dict[str, Any] = {}
        if affiliations:
            sd["affiliations"] = affiliations
        # `authenticated-orcid` n'est pas fiable côté CrossRef (la quasi
        # totalité des ORCIDs sont à False parce que les éditeurs n'utilisent
        # pas le workflow OAuth) — on le stocke pour traçabilité mais on ne
        # s'en sert pas comme filtre de confiance.
        if author.get("authenticated-orcid") is True:
            sd["authenticated_orcid"] = True
        if author.get("sequence"):
            sd["sequence"] = author["sequence"]
        source_data = Json(sd) if sd else None

        queries.upsert_crossref_source_authorship(
            cur,
            source_publication_id=source_publication_id,
            source_person_id=source_person_id,
            author_position=position,
            raw_author_name=full_name,
            source_data=source_data,
        )


# =============================================================
# PUBLICATION (rattachement à la table de vérité)
# =============================================================


def find_publication(
    cur: Any,
    msg: dict,
    journal_id: int | None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche la publi canonique pour un record CrossRef, sans la créer.

    Le matching est en pratique presque toujours par DOI (CrossRef = DOI-driven).
    En phase 1, on passe ``doc_type='other'`` à ``find_or_create`` (le mapping
    CrossRef → enum canonique vit en phase 2), suffisant pour le matching DOI.
    """
    title = get_title(msg)
    pub_year = get_pub_year(msg)
    doi = get_doi(msg)
    if not doi or not title or not pub_year:
        return None
    pub_id, _ = find_or_create_publication(
        cur,
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
    cur: Any,
    queries: CrossrefNormalizeQueries,
    logger: Any,
    staging_row: Any,
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
) -> bool | None:
    staging_id = staging_row["id"]
    raw = staging_row["raw_data"]
    if not isinstance(raw, dict) or not raw:
        # Stub not_found ou payload vide — devrait déjà être processed=TRUE,
        # par sécurité on marque processed et on passe.
        staging_queries.mark_done(cur, staging_id)
        return None

    msg = raw  # CrossRef stocke directement le 'message'
    doi = get_doi(msg)
    if not doi:
        logger.warning(f"CrossRef staging {staging_id} sans DOI exploitable — skip")
        staging_queries.mark_done(cur, staging_id)
        return None

    title = get_title(msg)
    pub_year = get_pub_year(msg)
    if not title or not pub_year:
        logger.warning(
            f"CrossRef {doi} sans titre ou année — pas de rattachement possible, skip"
        )
        staging_queries.mark_done(cur, staging_id)
        return None

    publisher_id = upsert_publisher(cur, msg, publisher_repo=publisher_repo)
    journal_id = upsert_journal(cur, msg, publisher_id, journal_repo=journal_repo)

    publication_id = queries.get_crossref_publication_id(cur, doi)
    if not publication_id:
        publication_id = find_publication(cur, msg, journal_id, pub_repo=pub_repo)
    if publication_id:
        publication_id = try_merge_by_doi(cur, publication_id, doi, repo=pub_repo)

    external_ids = get_external_ids(msg)
    biblio = get_biblio(msg)
    meta = get_meta(msg)

    source_publication_id = queries.upsert_crossref_source_publication(
        cur,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=None,  # phase 2 fera le mapping (cf. docs/chantiers/crossref.md)
        publication_id=publication_id,
        staging_id=staging_id,
        external_ids=Json(external_ids) if external_ids else None,
        journal_id=journal_id,
        oa_status=None,
        language=get_language(msg),
        container_title=get_container_title(msg) if not journal_id else None,
        abstract=get_abstract(msg),
        keywords=get_keywords(msg),
        cited_by_count=get_cited_by_count(msg),
        biblio=Json(biblio) if biblio else None,
        meta=Json(meta) if meta else None,
    )

    process_authors(cur, queries, msg, doi, source_publication_id)

    if publication_id:
        refresh_from_sources(cur, publication_id, repo=pub_repo)

    staging_queries.mark_done(cur, staging_id)
    return True


class CrossrefNormalizer(SourceNormalizer):
    SOURCE = "crossref"
    DEFAULT_BATCH_SIZE = 100
    FETCH_COLUMNS = "id, source_id, doi, raw_data"

    def __init__(
        self,
        conn: Any,
        logger: Any,
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

    def preload_caches(self, cur: Any) -> None:
        self._journal_repo = self._journal_repo_factory(cur)
        self._publisher_repo = self._publisher_repo_factory(cur)
        self._pub_repo = self._pub_repo_factory(cur)

    def process_work(self, cur: Any, row: Any) -> bool | None:
        assert (
            self._journal_repo is not None
            and self._publisher_repo is not None
            and self._pub_repo is not None
        )
        return process_work(
            cur,
            self._queries,
            self.logger,
            row,
            journal_repo=self._journal_repo,
            publisher_repo=self._publisher_repo,
            pub_repo=self._pub_repo,
            staging_queries=self._staging,
        )
