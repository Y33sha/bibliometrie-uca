"""
Normalisation des données WoS : staging → tables normalisées.

Usage:
    python normalize_wos.py              # traiter tous les works non traités
    python normalize_wos.py --limit 100  # traiter N works (pour test)
    python normalize_wos.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                     (lien staging ↔ publication, source='wos')
    source_authorships                      (lien document × auteur, source='wos',
                                             avec `source_structures` TEXT[] = noms
                                             d'institutions et `person_identifiers` JSONB)

Format raw_data : structure WoS Expanded API (static_data, dynamic_data
imbriqués). L'ancien format TSV (fichiers téléchargés, clés 2 lettres
TI/AU/AF/SO/PU) n'est plus supporté.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Row

from application.journals import find_or_create_journal
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.normalize_wos import WosNormalizeQueries
from application.ports.staging import StagingQueries
from application.publications import find_or_create as find_or_create_publication
from application.publications import refresh_from_sources, try_merge_by_doi
from application.publishers import find_or_create_publisher
from domain.normalize import normalize_text
from domain.persons.identifiers import compact_identifiers, normalize_orcid
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi
from domain.publications.authorship_roles import map_role
from domain.publications.doc_types import map_doc_type
from domain.sources.wos import derive_wos_api_oa_status, is_wos_author_exploitable

# =============================================================
# UTILITAIRES
# =============================================================


def _safe_list(obj: Any) -> list:
    """WoS API retourne parfois un dict au lieu d'une liste."""
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    return [obj]


def _get_api_title(static: dict, title_type: str) -> str | None:
    """Extrait un titre depuis la structure API."""
    titles = static.get("summary", {}).get("titles", {})
    title_list = _safe_list(titles.get("title"))
    for t in title_list:
        if isinstance(t, dict) and t.get("type") == title_type:
            return t.get("content")
    return None


def _parse_api_authors(static: dict, dynamic: dict) -> list[dict]:
    """Extrait les auteurs depuis le format API."""
    names_data = static.get("summary", {}).get("names", {})
    name_list = _safe_list(names_data.get("name"))

    # Adresses pour le matching
    addresses_data = static.get("fullrecord_metadata", {}).get("addresses", {})
    addr_list = _safe_list(addresses_data.get("address_name"))
    addr_map = {}  # addr_no -> full_address
    addr_orgs_map = {}  # addr_no -> [{name, ror_id, country}]
    for addr_entry in addr_list:
        spec = addr_entry.get("address_spec", {})
        addr_no = spec.get("addr_no")
        if addr_no is not None:
            addr_map[str(addr_no)] = spec.get("full_address", "")
            # Organizations structurées
            orgs_data = spec.get("organizations", {})
            org_list = _safe_list(orgs_data.get("organization"))
            orgs = []
            for o in org_list:
                if isinstance(o, dict) and o.get("content"):
                    orgs.append(
                        {
                            "name": o["content"],
                            "ror_id": o.get("ror_id"),
                            "pref": o.get("pref"),
                        }
                    )
            if orgs:
                addr_orgs_map[str(addr_no)] = orgs

    authors = []
    for name_obj in name_list:
        if not isinstance(name_obj, dict):
            continue
        wos_role = name_obj.get("role")
        if not wos_role:
            continue

        full_name = name_obj.get("display_name") or name_obj.get("full_name") or ""
        last_name = name_obj.get("last_name")
        first_name = name_obj.get("first_name")
        seq_no = name_obj.get("seq_no")
        position = int(seq_no) - 1 if seq_no else 0

        daisng_id = name_obj.get("daisng_id")
        if daisng_id:
            daisng_id = str(daisng_id)
        researcher_id = name_obj.get("r_id")

        # ORCID depuis data-item-ids
        orcid = None
        di_ids = name_obj.get("data-item-ids", {})
        di_list = _safe_list(di_ids.get("data-item-id"))
        for di in di_list:
            if isinstance(di, dict) and di.get("id-type") == "PreferredORCID":
                orcid = normalize_orcid(di.get("content"))
                break

        is_corresponding = name_obj.get("reprint") == "Y"

        # Affiliations via addr_no
        addr_nos = name_obj.get("addr_no")
        raw_affiliation = None
        individual_addresses = []
        author_orgs = []
        if addr_nos:
            addr_no_list = str(addr_nos).split()
            affils = [addr_map[a] for a in addr_no_list if a in addr_map]
            individual_addresses = [a.strip() for a in affils if a.strip()]
            if affils:
                raw_affiliation = " | ".join(affils)
            # Collecter les organizations de cet auteur
            seen_org_names = set()
            for a_no in addr_no_list:
                for org in addr_orgs_map.get(a_no, []):
                    if org["name"] not in seen_org_names:
                        author_orgs.append(org)
                        seen_org_names.add(org["name"])

        roles, is_corresponding_from_role = map_role("wos", wos_role)
        is_corresponding = is_corresponding or is_corresponding_from_role

        authors.append(
            {
                "position": position,
                "full_name": full_name.strip(),
                "last_name": last_name,
                "first_name": first_name,
                "orcid": orcid,
                "researcher_id": researcher_id,
                "daisng_id": daisng_id,
                "is_corresponding": is_corresponding,
                "raw_affiliation": raw_affiliation,
                "addresses": individual_addresses,
                "organizations": author_orgs,
                "roles": roles,
            }
        )

    return authors


def _get_api_doi(dynamic: dict) -> str | None:
    """Extrait le DOI depuis la structure API."""
    try:
        identifiers = (
            dynamic.get("cluster_related", {}).get("identifiers", {}).get("identifier", [])
        )
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == "doi":
                return clean_doi(str(ident.get("value", "")))
    except (KeyError, TypeError):
        pass
    return None


def _get_api_issn(dynamic: dict, issn_type: str = "issn") -> str | None:
    """Extrait l'ISSN ou eISSN depuis la structure API."""
    try:
        identifiers = (
            dynamic.get("cluster_related", {}).get("identifiers", {}).get("identifier", [])
        )
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == issn_type:
                return str(ident.get("value", "")).strip() or None
    except (KeyError, TypeError):
        pass
    return None


def extract_from_api(raw: dict, staging_doi: str | None) -> dict:
    """Extrait un record structuré depuis le format API."""
    static = raw.get("static_data", {})
    dynamic = raw.get("dynamic_data", {})
    summary = static.get("summary", {})
    pub_info = summary.get("pub_info", {})

    doi = _get_api_doi(dynamic) or clean_doi(staging_doi)
    title = _get_api_title(static, "item") or "(sans titre)"

    pub_year = None
    py = pub_info.get("pubyear")
    if py:
        try:
            pub_year = int(py)
        except ValueError:
            pass

    # Doc type
    doctypes = summary.get("doctypes", {})
    doctype_list = _safe_list(doctypes.get("doctype") if isinstance(doctypes, dict) else doctypes)
    raw_doc_type = None
    if doctype_list:
        if isinstance(doctype_list[0], dict):
            raw_doc_type = doctype_list[0].get("content", "")
        else:
            raw_doc_type = str(doctype_list[0])

    # Publisher
    publishers = summary.get("publishers", {})
    pub_data = publishers.get("publisher", {})
    pub_names = pub_data.get("names", {})
    pub_name_obj = pub_names.get("name", {})
    if isinstance(pub_name_obj, list):
        pub_name_obj = pub_name_obj[0] if pub_name_obj else {}
    publisher_name = pub_name_obj.get("unified_name") or pub_name_obj.get("full_name")

    # Journal
    journal_title = _get_api_title(static, "source")

    oa_status = derive_wos_api_oa_status(pub_info.get("journal_oas_gold"))

    # Language
    lang_data = static.get("fullrecord_metadata", {}).get("languages", {})
    lang_list = _safe_list(lang_data.get("language"))
    language = None
    if lang_list and isinstance(lang_list[0], dict):
        language = lang_list[0].get("content")
    elif lang_list:
        language = str(lang_list[0])

    # Biblio
    page = pub_info.get("page", {})
    if isinstance(page, str):
        page = {}
    biblio = {}
    vol = pub_info.get("vol")
    if vol:
        biblio["volume"] = str(vol)
    issue_val = pub_info.get("issue")
    if issue_val:
        biblio["issue"] = str(issue_val)
    if isinstance(page, dict):
        if page.get("begin"):
            biblio["first_page"] = str(page["begin"])
        if page.get("end"):
            biblio["last_page"] = str(page["end"])

    # Abstract
    frm = static.get("fullrecord_metadata", {})
    abstract = None
    abstracts = frm.get("abstracts", {})
    if abstracts:
        ab = abstracts.get("abstract", {})
        p = ab.get("abstract_text", {}).get("p", "")
        if isinstance(p, list):
            p = " ".join(str(x) for x in p)
        if p:
            abstract = str(p)

    # Keywords
    kw_data = frm.get("keywords", {})
    kw_list = kw_data.get("keyword", []) if isinstance(kw_data, dict) else []
    if isinstance(kw_list, str):
        kw_list = [kw_list]
    keywords = [str(k) for k in kw_list if k] or None

    # Topics : categories
    cat = frm.get("category_info", {})
    topics = {}
    subjects = cat.get("subjects", {}).get("subject", [])
    if isinstance(subjects, dict):
        subjects = [subjects]
    subj_names = [
        s.get("content") or s for s in subjects if isinstance(s, dict) and s.get("content")
    ]
    if subj_names:
        topics["subjects"] = subj_names
    headings = cat.get("headings", {}).get("heading", [])
    if isinstance(headings, str):
        headings = [headings]
    if headings:
        topics["headings"] = headings

    # Citations
    tc_list = dynamic.get("citation_related", {}).get("tc_list", {}).get("silo_tc", [])
    if isinstance(tc_list, dict):
        tc_list = [tc_list]
    cited_by_count = None
    for tc in tc_list:
        if isinstance(tc, dict) and tc.get("coll_id") == "WOK":
            try:
                cited_by_count = int(tc.get("local_count", 0))
            except (ValueError, TypeError):
                pass

    return {
        "ut": raw.get("UID", ""),
        "doi": doi,
        "title": title,
        "pub_year": pub_year,
        "doc_type": raw_doc_type or "other",
        "language": language,
        "oa_status": oa_status,
        "journal_title": journal_title,
        "issn": _get_api_issn(dynamic, "issn"),
        "eissn": _get_api_issn(dynamic, "eissn"),
        "publisher_name": publisher_name,
        "authors": _parse_api_authors(static, dynamic),
        "abstract": abstract,
        "cited_by_count": cited_by_count,
        "biblio": biblio or None,
        "keywords": keywords,
        "topics": topics or None,
        "urls": None,
        "external_ids": None,
    }


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================


def upsert_publisher(
    publisher_name: str | None, *, publisher_repo: PublisherRepository
) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(publisher_name, repo=publisher_repo)


def upsert_journal(
    rec: dict, publisher_id: int | None, *, journal_repo: JournalRepository
) -> int | None:
    """Trouve ou crée une revue depuis les données WoS."""
    title = rec.get("journal_title")
    if not title:
        return None
    return find_or_create_journal(
        title,
        issn=rec.get("issn"),
        eissn=rec.get("eissn"),
        publisher_id=publisher_id,
        repo=journal_repo,
    )


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================


def extract_pub_metadata(rec: dict, journal_id: int | None) -> dict:
    """Extrait les métadonnées de publication d'un record WoS.

    Retourne un dict utilisable par find_or_create_publication.
    """
    title = rec["title"]
    container_title = rec.get("journal_title") if not journal_id else None

    return dict(
        title=title,
        title_normalized=normalize_text(title),
        pub_year=rec["pub_year"],
        doc_type=rec["doc_type"],
        doi=rec["doi"],
        oa_status=rec["oa_status"],
        journal_id=journal_id,
        container_title=container_title,
        language=rec.get("language"),
    )


def find_publication(
    rec: dict,
    journal_id: int | None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(rec, journal_id)
    if not meta["pub_year"] or not meta["title"] or meta["title"] == "(sans titre)":
        return None
    # Mapper le doc_type pour find_or_create (resolve_doi_conflict a besoin du type canonique)
    meta["doc_type"] = map_doc_type(meta["doc_type"], "wos")
    pub_id, _ = find_or_create_publication(**meta, allow_create=False, repo=pub_repo)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (WOS)
# =============================================================


def insert_wos_document(
    conn: Connection,
    queries: WosNormalizeQueries,
    rec: dict,
    staging_id: int,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    """Crée/retrouve l'entrée source_publications pour WoS. Retourne source_publications.id."""
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    abstract = rec.get("abstract")
    cited_by_count = rec.get("cited_by_count")
    biblio = rec.get("biblio")
    keywords = rec.get("keywords")
    topics = rec.get("topics")
    urls = rec.get("urls")
    external_ids = rec.get("external_ids")

    return queries.upsert_wos_source_publication(
        conn,
        ut=rec["ut"],
        doi=rec["doi"],
        title=rec["title"],
        pub_year=rec["pub_year"],
        doc_type=rec["doc_type"],
        publication_id=publication_id,
        staging_id=staging_id,
        journal_id=journal_id,
        oa_status=oa_status,
        language=language,
        container_title=container_title,
        abstract=abstract,
        cited_by_count=cited_by_count,
        biblio=biblio,
        keywords=keywords,
        topics=topics,
        urls=urls,
        external_ids=external_ids,
    )


# =============================================================
# WOS AUTHORSHIPS — identifiants sur source_authorships
# =============================================================
# Le `daisng_id` (entité algorithmique WoS non fiable) n'est pas
# conservé. Le `researcher_id` (ResearcherID Clarivate) — identifiant
# cross-source — vit sur source_authorships.person_identifiers.


def _resolve_addresses_batch(
    conn: Connection, queries: WosNormalizeQueries, raw_texts: set
) -> dict[str, int]:
    """Résout un ensemble d'adresses en batch. Retourne {raw_text: id}."""
    if not raw_texts:
        return {}
    values = [{"raw": t, "norm": normalize_text(t)} for t in raw_texts]
    queries.upsert_addresses_batch(conn, values)
    return queries.fetch_address_ids_by_raw_text(conn, list(raw_texts))


def process_authorships(
    conn: Connection, queries: WosNormalizeQueries, rec: dict, source_publication_id: int
) -> None:
    """Traite les authorships d'un record WoS + crée les liens adresses.

    Chaque authorship porte un dict `person_identifiers` (orcid +
    researcher_id) et `source_structures` (TEXT[] des noms d'organisations
    WoS — seul identifiant stable disponible côté WoS).
    """
    # Pré-nettoyage : re-traitement → table blanche pour cette publi.
    queries.clear_source_authorships_for_publication(conn, source_publication_id)

    # Filtrer les auteurs exploitables (cf. `is_wos_author_exploitable`
    # pour la sémantique du filtre).
    authors_kept = [a for a in rec.get("authors", []) if is_wos_author_exploitable(a)]
    if not authors_kept:
        return

    # Batch INSERT source_authorships (person_identifiers JSONB,
    # source_structures TEXT[]).
    from domain.normalize import normalize_name_form

    values = {}  # clé = author_position, dédupliqué (1 row par position)
    for author in authors_kept:
        position = author["position"]
        if position in values:
            continue  # même position déjà traitée

        # Noms des institutions WoS comme identifiants natifs (TEXT[]).
        # Pas d'ID stable côté WoS — le nom sert d'identifiant.
        institution_names = [
            org["name"] for org in author.get("organizations", []) if org.get("name")
        ]

        name_norm = normalize_name_form(author["full_name"])
        ids = compact_identifiers(
            orcid=author.get("orcid"),
            researcher_id=author.get("researcher_id"),
        )

        values[position] = {
            "spid": source_publication_id,
            "author_position": position,
            "is_corresponding": author["is_corresponding"],
            "author_name_normalized": name_norm,
            "source_structures": institution_names or None,
            "roles": author.get("roles"),
            "raw_author_name": author["full_name"],
            "person_identifiers": ids if ids else None,
        }

    queries.upsert_wos_source_authorships_batch(conn, list(values.values()))

    # Phase 3 : batch adresses — pivot par author_position.
    authors_with_addrs = [a for a in authors_kept if a.get("addresses")]
    if authors_with_addrs:
        # Collecter toutes les adresses uniques du document
        all_addr_texts = set()
        for author in authors_with_addrs:
            all_addr_texts.update(author["addresses"])

        addr_id_map = _resolve_addresses_batch(conn, queries, all_addr_texts)

        positions_needed = [a["position"] for a in authors_with_addrs]
        sa_id_map = queries.fetch_source_authorship_ids_by_position(
            conn, source_publication_id=source_publication_id, positions=positions_needed
        )

        addr_values: list[dict[str, int]] = []
        for author in authors_with_addrs:
            sa_id = sa_id_map.get(author["position"])
            if not sa_id:
                continue
            for addr_text in author["addresses"]:
                addr_id = addr_id_map.get(addr_text)
                if addr_id:
                    addr_values.append({"sa_id": sa_id, "addr_id": addr_id})

        queries.insert_source_authorship_addresses_batch(conn, addr_values)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_record(
    conn: Connection,
    queries: WosNormalizeQueries,
    logger: logging.Logger,
    staging_row: Row[Any],
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
) -> bool:
    """Traite un record du staging WoS. Retourne True si succès."""
    from application.pipeline.timings import StepTimer

    staging_id, ut, staging_doi, raw_data = staging_row

    try:
        t = StepTimer()
        rec = extract_from_api(raw_data, staging_doi)

        if not rec["ut"]:
            rec["ut"] = ut

        publisher_id = upsert_publisher(rec.get("publisher_name"), publisher_repo=publisher_repo)
        journal_id = upsert_journal(rec, publisher_id, journal_repo=journal_repo)
        t.mark("publisher+journal")

        pub_meta = extract_pub_metadata(rec, journal_id)

        publication_id = queries.get_wos_publication_id(conn, rec["ut"])

        if not publication_id:
            publication_id = find_publication(rec, journal_id, pub_repo=pub_repo)
        t.mark("publication")

        if publication_id:
            publication_id = try_merge_by_doi(publication_id, pub_meta["doi"], repo=pub_repo)

        source_publication_id = insert_wos_document(
            conn, queries, rec, staging_id, publication_id, pub_meta
        )
        t.mark("wos_doc")

        process_authorships(conn, queries, rec, source_publication_id)
        t.mark("authors")

        if publication_id:
            refresh_from_sources(publication_id, repo=pub_repo)
        t.mark("refresh")

        staging_queries.mark_done(conn, staging_id)
        t.log_if_slow(ut, logger)
        return True

    except Exception as e:
        logger.error(f"Erreur sur {ut}: {e}")
        raise


class WosNormalizer(SourceNormalizer):
    SOURCE = "wos"
    DEFAULT_BATCH_SIZE = 500
    USE_DICT_CURSOR = False
    USE_SAVEPOINT = True
    FETCH_SUB_BATCH = 50
    FETCH_COLUMNS = "id, source_id AS ut, doi, raw_data"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: WosNormalizeQueries,
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
        return process_record(
            conn,
            self._queries,
            self.logger,
            row,
            journal_repo=self._journal_repo,
            publisher_repo=self._publisher_repo,
            pub_repo=self._pub_repo,
            staging_queries=self._staging,
        )
