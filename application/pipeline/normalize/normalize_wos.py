"""Normalisation des données WoS : staging → tables normalisées."""

import logging
from collections.abc import Mapping, Sequence

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
from domain.persons.identifiers import (
    compact_identifiers,
    mark_shared_identifiers_dubious,
)
from domain.publications.authorship_roles import map_role
from domain.publications.identifiers import clean_doi
from domain.sources.wos import derive_wos_api_oa_status, is_wos_author_exploitable
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str

# =============================================================
# UTILITAIRES
# =============================================================


def _safe_list(obj: JsonValue) -> Sequence[JsonValue]:
    """Suite de valeurs portée par `obj` : l'API rend un objet seul là où elle annonce une liste."""
    if obj is None:
        return []
    if isinstance(obj, str | Mapping):
        return [obj]
    if isinstance(obj, Sequence):
        return obj
    return [obj]


def _chemin(racine: JsonValue, *cles: str) -> Mapping[str, JsonValue]:
    """Objet atteint en descendant `cles` depuis `racine`, ou un objet vide.

    Le format de l'API décalque un schéma XML : ses champs se nichent sous cinq ou six niveaux d'objets, dont chacun peut manquer. Descendre par cette fonction évite d'avoir à le vérifier niveau par niveau.
    """
    courant = as_mapping(racine)
    for cle in cles:
        courant = as_mapping(courant.get(cle))
    return courant


def _get_api_title(static: Mapping[str, JsonValue], title_type: str) -> str | None:
    """Extrait un titre depuis la structure API."""
    titles = _chemin(static, "summary", "titles")
    title_list = _safe_list(titles.get("title"))
    for entree in title_list:
        t = as_mapping(entree)
        if as_str(t.get("type")) == title_type:
            return as_str(t.get("content"))
    return None


def _parse_api_authors(
    static: Mapping[str, JsonValue], dynamic: Mapping[str, JsonValue]
) -> list[dict[str, JsonValue]]:
    """Extrait les auteurs depuis le format API."""
    names_data = _chemin(static, "summary", "names")
    name_list = _safe_list(names_data.get("name"))

    # Adresses pour le matching
    addresses_data = _chemin(static, "fullrecord_metadata", "addresses")
    addr_list = _safe_list(addresses_data.get("address_name"))
    addr_map: dict[str, str] = {}  # addr_no -> full_address
    addr_orgs_map: dict[str, list[dict[str, JsonValue]]] = {}  # addr_no -> [{name, ror_id, pref}]
    for addr_entry in addr_list:
        spec = _chemin(addr_entry, "address_spec")
        addr_no = spec.get("addr_no")
        if addr_no is not None:
            addr_map[str(addr_no)] = as_str(spec.get("full_address")) or ""
            # Organizations structurées
            org_list = _safe_list(_chemin(spec, "organizations").get("organization"))
            orgs: list[dict[str, JsonValue]] = []
            for entree in org_list:
                o = as_mapping(entree)
                if nom := as_str(o.get("content")):
                    orgs.append({"name": nom, "ror_id": o.get("ror_id"), "pref": o.get("pref")})
            if orgs:
                addr_orgs_map[str(addr_no)] = orgs

    authors: list[dict[str, JsonValue]] = []
    for entree in name_list:
        name_obj = as_mapping(entree)
        wos_role = as_str(name_obj.get("role"))
        if not wos_role:
            continue

        full_name = as_str(name_obj.get("display_name")) or as_str(name_obj.get("full_name")) or ""
        last_name = as_str(name_obj.get("last_name"))
        first_name = as_str(name_obj.get("first_name"))
        seq_no = as_int(name_obj.get("seq_no")) or as_str(name_obj.get("seq_no"))
        position = int(seq_no) - 1 if seq_no else 0

        daisng = name_obj.get("daisng_id")
        daisng_id = str(daisng) if daisng else None
        researcher_id = as_str(name_obj.get("r_id"))

        # L'ORCID WoS (`PreferredORCID`) n'est pas moissonné : attribué par le matching algorithmique interne de Web of Science, il est trop peu fiable pour figurer sur l'identité d'auteur (où sa source serait perdue et où il deviendrait un faux signal de matching).
        # Les ORCID fiables viennent des sources à dépôt auteur (Crossref, OpenAlex `raw_orcid`, HAL).

        is_corresponding = as_str(name_obj.get("reprint")) == "Y"

        # Affiliations via addr_no
        addr_nos = name_obj.get("addr_no")
        raw_affiliation = None
        individual_addresses: list[str] = []
        author_orgs: list[dict[str, JsonValue]] = []
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
                    nom = as_str(org["name"])
                    if nom and nom not in seen_org_names:
                        author_orgs.append(org)
                        seen_org_names.add(nom)

        roles, is_corresponding_from_role = map_role("wos", wos_role)
        is_corresponding = is_corresponding or is_corresponding_from_role

        authors.append(
            {
                "position": position,
                "full_name": full_name.strip(),
                "last_name": last_name,
                "first_name": first_name,
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


def _get_api_doi(dynamic: Mapping[str, JsonValue]) -> str | None:
    """Extrait le DOI depuis la structure API."""
    try:
        identifiers = _chemin(dynamic, "cluster_related", "identifiers").get("identifier", [])
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == "doi":
                return clean_doi(str(ident.get("value", "")))
    except (KeyError, TypeError):
        pass
    return None


def _get_api_issn(dynamic: Mapping[str, JsonValue], issn_type: str = "issn") -> str | None:
    """Extrait l'ISSN ou eISSN depuis la structure API."""
    try:
        identifiers = _chemin(dynamic, "cluster_related", "identifiers").get("identifier", [])
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == issn_type:
                return str(ident.get("value", "")).strip() or None
    except (KeyError, TypeError):
        pass
    return None


def extract_from_api(raw: Mapping[str, JsonValue], staging_doi: str | None) -> dict[str, JsonValue]:  # noqa: C901
    """Extrait un record structuré depuis le format API."""
    static = _chemin(raw, "static_data")
    dynamic = _chemin(raw, "dynamic_data")
    summary = _chemin(static, "summary")
    pub_info = _chemin(summary, "pub_info")

    doi = _get_api_doi(dynamic) or clean_doi(staging_doi)
    title = _get_api_title(static, "item") or "(sans titre)"

    pub_year = as_int(pub_info.get("pubyear"))
    if pub_year is None and (py := as_str(pub_info.get("pubyear"))):
        try:
            pub_year = int(py)
        except ValueError:
            pass

    # Doc type
    doctypes = _chemin(summary, "doctypes")
    doctype_list = _safe_list(doctypes.get("doctype"))
    raw_doc_type = None
    if doctype_list:
        premier = doctype_list[0]
        raw_doc_type = as_str(as_mapping(premier).get("content")) or as_str(premier)

    # Publisher
    publishers = _chemin(summary, "publishers")
    pub_data = _chemin(publishers, "publisher")
    pub_names = _chemin(pub_data, "names")
    noms = _safe_list(pub_names.get("name"))
    pub_name_obj = as_mapping(noms[0]) if noms else {}
    publisher_name = as_str(pub_name_obj.get("unified_name")) or as_str(
        pub_name_obj.get("full_name")
    )

    # Journal
    journal_title = _get_api_title(static, "source")

    oa_status = derive_wos_api_oa_status(as_str(pub_info.get("journal_oas_gold")))

    # Language
    lang_data = _chemin(static, "fullrecord_metadata", "languages")
    lang_list = _safe_list(lang_data.get("language"))
    language = None
    if lang_list:
        language = as_str(as_mapping(lang_list[0]).get("content")) or as_str(lang_list[0])

    # Biblio
    page = _chemin(pub_info, "page")
    if isinstance(page, str):
        page = {}
    biblio: dict[str, JsonValue] = {}
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

    # Publisher + journal bruts (traçabilité du nom tel que vu par WoS, en parallèle des publishers/journals créés via find_or_create_*).
    issn_val = _get_api_issn(dynamic, "issn")
    eissn_val = _get_api_issn(dynamic, "eissn")
    if publisher_name:
        biblio["publisher"] = publisher_name
    journal_obj: dict[str, str] = {}
    if journal_title:
        journal_obj["title"] = journal_title
    if issn_val:
        journal_obj["issn"] = issn_val
    if eissn_val:
        journal_obj["eissn"] = eissn_val
    if journal_obj:
        biblio["journal"] = journal_obj

    # Abstract
    frm = _chemin(static, "fullrecord_metadata")
    abstract = None
    abstracts = _chemin(frm, "abstracts")
    if abstracts:
        ab = _chemin(abstracts, "abstract")
        p = _chemin(ab, "abstract_text").get("p", "")
        if isinstance(p, list):
            p = " ".join(str(x) for x in p)
        if p:
            abstract = str(p)

    # Keywords
    kw_data = _chemin(frm, "keywords")
    kw_list = kw_data.get("keyword", []) if isinstance(kw_data, dict) else []
    if isinstance(kw_list, str):
        kw_list = [kw_list]
    keywords = [str(k) for k in kw_list if k] or None

    # Topics : categories
    cat = _chemin(frm, "category_info")
    topics = {}
    subj_names = [
        nom
        for s in _safe_list(_chemin(cat, "subjects").get("subject"))
        if (nom := as_str(as_mapping(s).get("content")))
    ]
    if subj_names:
        topics["subjects"] = subj_names
    if headings := [
        h for e in _safe_list(_chemin(cat, "headings").get("heading")) if (h := as_str(e))
    ]:
        topics["headings"] = headings

    # Citations
    cited_by_count = None
    for entree in _safe_list(_chemin(dynamic, "citation_related", "tc_list").get("silo_tc")):
        tc = as_mapping(entree)
        if as_str(tc.get("coll_id")) == "WOK":
            # Compte absent : zéro citation. Compte illisible : le décompte reste inconnu.
            brut = tc.get("local_count")
            cited_by_count = 0 if brut is None else as_int(brut)

    return {
        "ut": raw.get("UID", ""),
        "doi": doi,
        "title": title,
        "pub_year": pub_year,
        "doc_type": raw_doc_type or "other",
        "language": language,
        "oa_status": oa_status,
        "journal_title": journal_title,
        "issn": issn_val,
        "eissn": eissn_val,
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
# PUBLISHERS & JOURNALS
# =============================================================


def upsert_publisher(
    publisher_name: str | None, *, publisher_repo: PublisherFindOrCreateQueries
) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(publisher_name, repo=publisher_repo)


def upsert_journal(
    rec: Mapping[str, JsonValue],
    publisher_id: int | None,
    *,
    journal_repo: JournalFindOrCreateQueries,
) -> int | None:
    """Trouve ou crée une revue depuis les données WoS."""
    title = as_str(rec.get("journal_title"))
    if not title:
        return None
    return find_or_create_journal(
        title,
        issn=as_str(rec.get("issn")),
        eissn=as_str(rec.get("eissn")),
        publisher_id=publisher_id,
        repo=journal_repo,
    )


# =============================================================
# PUBLICATIONS
# =============================================================


def extract_pub_metadata(
    rec: Mapping[str, JsonValue], journal_id: int | None
) -> PublicationMetadata:
    """Extrait les métadonnées canoniques d'un record WoS.

    Cette source ne porte pas de numéro national de thèse : elle ne moissonne pas les thèses.
    """
    return PublicationMetadata(
        title=as_str(rec.get("title")),
        pub_year=as_int(rec.get("pub_year")),
        doc_type=as_str(rec.get("doc_type")),
        doi=as_str(rec.get("doi")),
        nnt=None,
        oa_status=as_str(rec.get("oa_status")),
        journal_id=journal_id,
        container_title=as_str(rec.get("journal_title")) if not journal_id else None,
        language=as_str(rec.get("language")),
    )


# =============================================================
# SOURCE DOCUMENTS (WOS)
# =============================================================


def insert_wos_document(
    conn: Connection,
    queries: SourcePublicationQueries,
    rec: Mapping[str, JsonValue],
    staging_id: int,
    pub_meta: PublicationMetadata,
) -> int:
    """Crée/retrouve l'entrée source_publications pour WoS.

    Les métadonnées canoniques (doi, title, pub_year, doc_type, journal_id,
    oa_status, language, container_title) viennent toutes de `pub_meta`,
    construit en amont par `extract_pub_metadata`. `rec` ne sert ici
    que pour les extras WoS-spécifiques (abstract, cited_by_count, biblio,
    keywords, topics, urls, external_ids non canoniques).
    """
    return queries.upsert_source_publication(
        conn,
        SourcePublicationRow(
            source="wos",
            source_id=as_str(rec.get("ut")) or "",
            staging_id=staging_id,
            doi=pub_meta.doi,
            external_ids=dict(as_mapping(rec.get("external_ids"))) or None,
            title=pub_meta.title or "",
            pub_year=pub_meta.pub_year,
            doc_type=pub_meta.doc_type,
            journal_id=pub_meta.journal_id,
            container_title=pub_meta.container_title,
            language=pub_meta.language,
            biblio=dict(as_mapping(rec.get("biblio"))) or None,
            abstract=as_str(rec.get("abstract")),
            keywords=[k for e in as_sequence(rec.get("keywords")) if (k := as_str(e))] or None,
            topics=dict(as_mapping(rec.get("topics"))) or None,
            oa_status=pub_meta.oa_status,
            urls=[u for e in as_sequence(rec.get("urls")) if (u := as_str(e))] or None,
            cited_by_count=as_int(rec.get("cited_by_count")),
        ),
    )


# =============================================================
# WOS AUTHORSHIPS — identifiants sur source_authorships
# =============================================================
# Le `daisng_id` (entité algorithmique WoS non fiable) n'est pas conservé.
# Le `researcher_id` (ResearcherID Clarivate) — identifiant cross-source — vit sur l'identité de la signature (author_identifying_keys.person_identifiers).


def build_wos_author_records(
    rec: Mapping[str, JsonValue], logger: logging.Logger
) -> list[AuthorRecord]:
    """Parse les authorships d'un record WoS en `AuthorRecord` (sans I/O).

    Filtre les auteurs via `is_wos_author_exploitable` ; si aucun n'est exploitable alors que le record en porte, logge un warning (détecte une dérive éventuelle de l'API WoS — perte silencieuse de records sinon). Chaque auteur porte `person_identifiers` (researcher_id ; l'ORCID WoS n'est pas moissonné, cf. extraction) et ses adresses brutes. Les `author_position` du payload WoS peuvent se répéter ; elles sont dédoublonnées ici (première occurrence gagne), la clé `(source_publication_id, author_position)` interdisant les doublons en base.
    """
    raw_authors = [as_mapping(a) for a in as_sequence(rec.get("authors"))]
    authors_kept = [a for a in raw_authors if is_wos_author_exploitable(a)]
    if not authors_kept:
        if raw_authors:
            logger.warning(
                "WoS record %s : %d auteurs présents mais aucun exploitable "
                "(filtre is_wos_author_exploitable) — authorships ignorés",
                as_str(rec.get("ut")) or "?",
                len(raw_authors),
            )
        return []

    # Identifiant (researcher_id) partagé entre ≥2 signatures du record → `_dubious`.
    ids_by_position = mark_shared_identifiers_dubious(
        [compact_identifiers(researcher_id=as_str(a.get("researcher_id"))) for a in authors_kept]
    )

    records: list[AuthorRecord] = []
    for idx, author in enumerate(authors_kept):
        ids = ids_by_position[idx]
        records.append(
            AuthorRecord(
                position=as_int(author.get("position")) or 0,
                raw_name=as_str(author.get("full_name")) or "",
                is_corresponding=bool(author.get("is_corresponding")),
                roles=[role for e in as_sequence(author.get("roles")) if (role := as_str(e))]
                or None,
                person_identifiers=ids if ids else None,
                addresses=[
                    AddressRecord(text=adresse)
                    for e in as_sequence(author.get("addresses"))
                    if (adresse := as_str(e))
                ],
            )
        )
    # `author_position` lue du payload WoS : dédup (première occurrence gagne).
    by_position: dict[int, AuthorRecord] = {}
    for r in records:
        by_position.setdefault(r.position, r)
    return list(by_position.values())


def process_authorships(
    conn: Connection,
    authorship_queries: AuthorshipsBatchQueries,
    logger: logging.Logger,
    rec: Mapping[str, JsonValue],
    source_publication_id: int,
) -> None:
    """Parse les authorships WoS puis écrit en batch via le writer partagé."""
    records = build_wos_author_records(rec, logger)
    write_source_authorships(conn, authorship_queries, "wos", source_publication_id, records)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_record(
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
) -> bool:
    """Traite un record du staging WoS. Retourne True si succès."""
    staging_id = staging_row.id
    ut = staging_row.source_id
    staging_doi = staging_row.doi
    raw_data = staging_row.raw_data

    t = StepTimer()
    rec = extract_from_api(raw_data, staging_doi)

    if not rec["ut"]:
        rec["ut"] = ut

    publisher_id = upsert_publisher(
        as_str(rec.get("publisher_name")), publisher_repo=publisher_repo
    )
    journal_id = upsert_journal(rec, publisher_id, journal_repo=journal_repo)
    t.mark("publisher+journal")

    pub_meta = extract_pub_metadata(rec, journal_id)

    source_publication_id = insert_wos_document(conn, queries, rec, staging_id, pub_meta)
    t.mark("wos_doc")

    process_authorships(conn, authorship_queries, logger, rec, source_publication_id)
    t.mark("authors")

    staging_queries.mark_done(conn, staging_id)
    t.log_if_slow(ut, logger)
    return True


class WosNormalizer(BibliographicNormalizer):
    SOURCE = "wos"
    DEFAULT_BATCH_SIZE = 500

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        journal_repo, publisher_repo, publication_repo = self._require_repos()
        return process_record(
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
