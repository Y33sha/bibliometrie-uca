"""Normalisation des données WoS : staging → tables normalisées."""

import logging
from collections.abc import Mapping, Sequence
from functools import partial

from domain.journals.containers import ContainerDescription
from domain.journals.issns import source_issns
from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import ContributionRole, map_role
from domain.publications.identifiers import clean_doi, find_isbns
from domain.source_records.biblio import compact_biblio
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.impact import Impact
from domain.structures.identifiers import parse_ror_ids
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_strs, at_path
from pipeline.ingestion.common.normalizer import BibliographicNormalizer
from pipeline.ingestion.common.publication_metadata import PublicationMetadata
from pipeline.ingestion.common.source_contribution_store import SourceContributionStore
from pipeline.ingestion.common.source_contributions import (
    AddressRecord,
    AuthorBlock,
    AuthorRecord,
    contributor_identifiers,
    sync_source_contributions,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordStore,
    SourceRecordUpsert,
)
from pipeline.ingestion.common.staging import StagingRow, StagingStore
from pipeline.ingestion.wos.payload import (
    derive_wos_api_oa_status,
    is_wos_author_usable,
    parse_export_addresses,
    parse_export_corresponding,
    parse_export_researcher_ids,
    split_export_list,
)
from pipeline.transformation.publishing.containers import ContainerStores
from pipeline.transformation.publishing.find_or_create import (
    Containers,
    find_or_create_containers,
    find_or_create_publisher,
)
from pipeline.transformation.publishing.publishers.store import PublisherStore

# =============================================================
# UTILITAIRES
# =============================================================


def _text_of(value: JsonValue) -> str | None:
    """Numérotation que l'API donne en nombre ou en chaîne, en texte ; `None` si vide."""
    return str(value) if value else None


def _safe_list(obj: JsonValue) -> Sequence[JsonValue]:
    """Suite de valeurs portée par `obj` : l'API rend un objet seul là où elle annonce une liste."""
    if obj is None:
        return []
    if isinstance(obj, (str, Mapping)):
        return [obj]
    if isinstance(obj, Sequence):
        return obj
    return [obj]


def _get_api_title(static: Mapping[str, JsonValue], title_type: str) -> str | None:
    """Extrait un titre depuis la structure API."""
    titles = at_path(static, "summary", "titles")
    title_list = _safe_list(titles.get("title"))
    for entry in title_list:
        t = as_mapping(entry)
        if as_str(t.get("type")) == title_type:
            return as_str(t.get("content"))
    return None


def _parse_api_authors(
    static: Mapping[str, JsonValue], dynamic: Mapping[str, JsonValue]
) -> list[dict[str, JsonValue]]:
    """Extrait les auteurs depuis le format API."""
    names_data = at_path(static, "summary", "names")
    name_list = _safe_list(names_data.get("name"))

    # Adresses pour le matching
    addresses_data = at_path(static, "fullrecord_metadata", "addresses")
    addr_list = _safe_list(addresses_data.get("address_name"))
    addr_map: dict[str, str] = {}  # addr_no -> full_address
    addr_orgs_map: dict[str, list[dict[str, JsonValue]]] = {}  # addr_no -> [{name, ror_id, pref}]
    for addr_entry in addr_list:
        spec = at_path(addr_entry, "address_spec")
        addr_no = spec.get("addr_no")
        if addr_no is not None:
            addr_map[str(addr_no)] = as_str(spec.get("full_address")) or ""
            # Organizations structurées
            org_list = _safe_list(at_path(spec, "organizations").get("organization"))
            orgs: list[dict[str, JsonValue]] = []
            for entry in org_list:
                o = as_mapping(entry)
                if name := as_str(o.get("content")):
                    orgs.append({"name": name, "ror_id": o.get("ror_id"), "pref": o.get("pref")})
            if orgs:
                addr_orgs_map[str(addr_no)] = orgs

    authors: list[dict[str, JsonValue]] = []
    for entry in name_list:
        name_obj = as_mapping(entry)
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

        # L'ORCID WoS (`PreferredORCID`) n'est pas moissonné : attribué par le matching algorithmique interne de Web of Science, il est trop peu fiable pour figurer dans les informations du contributeur (où sa source serait perdue et où il deviendrait un faux signal de matching).
        # Les ORCID fiables viennent des sources à dépôt auteur (`ORCID_MATCH_SOURCES`).

        is_corresponding = as_str(name_obj.get("reprint")) == "Y"

        # Affiliations via addr_no
        addr_nos = name_obj.get("addr_no")
        raw_affiliation = None
        # Chaque adresse de l'auteur, avec les ROR de ses organisations.
        individual_addresses: list[dict[str, JsonValue]] = []
        if addr_nos:
            addr_no_list = [a for a in str(addr_nos).split() if a in addr_map]
            affils = [addr_map[a] for a in addr_no_list]
            if affils:
                raw_affiliation = " | ".join(affils)
            individual_addresses = [
                {
                    "text": addr_map[a].strip(),
                    "ror_ids": [
                        ror for org in addr_orgs_map.get(a, []) if (ror := as_str(org["ror_id"]))
                    ],
                }
                for a in addr_no_list
            ]

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
                "roles": roles,
            }
        )

    return authors


def _get_api_doi(dynamic: Mapping[str, JsonValue]) -> str | None:
    """Extrait le DOI depuis la structure API."""
    try:
        identifiers = at_path(dynamic, "cluster_related", "identifiers").get("identifier", [])
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == "doi":
                return clean_doi(str(ident.get("value", "")))
    except (KeyError, TypeError):
        pass
    return None


def _get_api_issn(dynamic: Mapping[str, JsonValue], issn_type: str = "issn") -> str | None:
    """Extrait l'ISSN ou eISSN depuis la structure API."""
    try:
        identifiers = at_path(dynamic, "cluster_related", "identifiers").get("identifier", [])
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == issn_type:
                return str(ident.get("value", "")).strip() or None
    except (KeyError, TypeError):
        pass
    return None


def _get_api_isbns(dynamic: Mapping[str, JsonValue], isbn_type: str) -> list[str]:
    """ISBN d'un support (`isbn` papier, `eisbn` électronique), que WoS distingue par le type de l'identifiant."""
    identifiers = at_path(dynamic, "cluster_related", "identifiers").get("identifier", [])
    isbns: list[str] = []
    for entry in _safe_list(identifiers):
        ident = as_mapping(entry)
        if as_str(ident.get("type")) == isbn_type:
            isbns += find_isbns(as_str(ident.get("value")))
    return list(dict.fromkeys(isbns))


def extract_from_api(raw: Mapping[str, JsonValue], staging_doi: str | None) -> dict[str, JsonValue]:  # noqa: C901
    """Extrait un record structuré depuis le format API."""
    static = at_path(raw, "static_data")
    dynamic = at_path(raw, "dynamic_data")
    summary = at_path(static, "summary")
    publication_info = at_path(summary, "pub_info")

    doi = _get_api_doi(dynamic) or clean_doi(staging_doi)
    title = _get_api_title(static, "item") or "(sans titre)"

    publication_year = as_int(publication_info.get("pubyear"))
    if publication_year is None and (py := as_str(publication_info.get("pubyear"))):
        try:
            publication_year = int(py)
        except ValueError:
            pass

    # Doc type
    doctypes = at_path(summary, "doctypes")
    doctype_list = _safe_list(doctypes.get("doctype"))
    raw_doc_type = None
    if doctype_list:
        first = doctype_list[0]
        raw_doc_type = as_str(as_mapping(first).get("content")) or as_str(first)

    # Publisher
    publishers = at_path(summary, "publishers")
    publisher_data = at_path(publishers, "publisher")
    publisher_names = at_path(publisher_data, "names")
    names = _safe_list(publisher_names.get("name"))
    publisher_name_obj = as_mapping(names[0]) if names else {}
    publisher_name = as_str(publisher_name_obj.get("unified_name")) or as_str(
        publisher_name_obj.get("full_name")
    )

    # Journal
    journal_title = _get_api_title(static, "source")

    oa_status = derive_wos_api_oa_status(as_str(publication_info.get("journal_oas_gold")))

    # Language
    lang_data = at_path(static, "fullrecord_metadata", "languages")
    lang_list = _safe_list(lang_data.get("language"))
    language = None
    if lang_list:
        language = as_str(as_mapping(lang_list[0]).get("content")) or as_str(lang_list[0])

    # Numérotation, éditeur et revue tels que WoS les nomme, en parallèle des publishers/journals créés via find_or_create_*.
    page = at_path(publication_info, "page")
    issn_val = _get_api_issn(dynamic, "issn")
    eissn_val = _get_api_issn(dynamic, "eissn")
    biblio = compact_biblio(
        volume=_text_of(publication_info.get("vol")),
        issue=_text_of(publication_info.get("issue")),
        first_page=_text_of(page.get("begin")),
        last_page=_text_of(page.get("end")),
        publisher=publisher_name,
        journal_title=journal_title,
        journal_issn=issn_val,
        journal_eissn=eissn_val,
    )

    # Abstract
    frm = at_path(static, "fullrecord_metadata")
    abstract = None
    abstracts = at_path(frm, "abstracts")
    if abstracts:
        ab = at_path(abstracts, "abstract")
        p = at_path(ab, "abstract_text").get("p", "")
        if isinstance(p, list):
            p = " ".join(str(x) for x in p)
        if p:
            abstract = str(p)

    # Keywords
    # Web of Science rend un mot-clé unique en chaîne, plusieurs en liste.
    kw_raw = at_path(frm, "keywords").get("keyword", [])
    single_word = as_str(kw_raw)
    keywords = ([single_word] if single_word else as_strs(kw_raw)) or None

    # Topics : categories
    cat = at_path(frm, "category_info")
    topics = {}
    subj_names = [
        name
        for s in _safe_list(at_path(cat, "subjects").get("subject"))
        if (name := as_str(as_mapping(s).get("content")))
    ]
    if subj_names:
        topics["subjects"] = subj_names
    if headings := [
        h for e in _safe_list(at_path(cat, "headings").get("heading")) if (h := as_str(e))
    ]:
        topics["headings"] = headings

    # Citations
    cited_by_count = None
    for entry in _safe_list(at_path(dynamic, "citation_related", "tc_list").get("silo_tc")):
        tc = as_mapping(entry)
        if as_str(tc.get("coll_id")) == "WOK":
            # Compte absent : zéro citation. Compte illisible : le décompte reste inconnu.
            local_count = tc.get("local_count")
            cited_by_count = 0 if local_count is None else as_int(local_count)

    authors = _parse_api_authors(static, dynamic)
    return {
        "ut": raw.get("UID", ""),
        "doi": doi,
        "title": title,
        "publication_year": publication_year,
        "doc_type": raw_doc_type or "other",
        "language": language,
        "oa_status": oa_status,
        "journal_title": journal_title,
        "issn": issn_val,
        "eissn": eissn_val,
        "publisher_name": publisher_name,
        "authors": [a for a in authors if is_wos_author_usable(a)],
        "authors_found": len(authors),
        "abstract": abstract,
        "cited_by_count": cited_by_count,
        "biblio": biblio or None,
        "keywords": keywords,
        "topics": topics or None,
        "urls": None,
        "external_ids": {
            key: isbns
            for key, isbns in (
                (ExternalIdType.ISBN, _get_api_isbns(dynamic, "isbn")),
                (ExternalIdType.EISBN, _get_api_isbns(dynamic, "eisbn")),
            )
            if isbns
        }
        or None,
    }


def _export_authors(raw: Mapping[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Auteurs d'une ligne d'export, dans l'ordre de `AF` (noms complets) et `AU` (noms abrégés)."""
    full_names = split_export_list(as_str(raw.get("AF")))
    short_names = split_export_list(as_str(raw.get("AU")))
    addresses = parse_export_addresses(as_str(raw.get("C1")))
    corresponding = parse_export_corresponding(as_str(raw.get("RP")))
    researcher_ids = parse_export_researcher_ids(as_str(raw.get("RI")))
    roles, _ = map_role("wos", "author")
    authors: list[dict[str, JsonValue]] = []
    for position, full_name in enumerate(full_names):
        key = normalize_text(full_name)
        short_name = short_names[position] if position < len(short_names) else ""
        author_addresses = addresses.get(key, [])
        last_name, _, first_name = full_name.partition(", ")
        authors.append(
            {
                "position": position,
                "full_name": full_name,
                "last_name": last_name.strip() or None,
                "first_name": first_name.strip() or None,
                "researcher_id": researcher_ids.get(key),
                "is_corresponding": normalize_text(short_name) in corresponding,
                "raw_affiliation": " | ".join(author_addresses) or None,
                "addresses": [{"text": a, "ror_ids": []} for a in author_addresses],
                "roles": roles,
            }
        )
    return authors


def extract_from_export(
    raw: Mapping[str, JsonValue], staging_doi: str | None
) -> dict[str, JsonValue]:
    """Extrait un record structuré d'une ligne d'export tabulé de l'interface WoS, sous la même forme qu'`extract_from_api`. Le statut open access reste inconnu."""

    def field(tag: str) -> str | None:
        return as_str(raw.get(tag))

    biblio = compact_biblio(
        volume=field("VL"),
        issue=field("IS"),
        first_page=field("BP"),
        last_page=field("EP"),
        publisher=field("PU"),
        journal_title=field("SO"),
        journal_issn=field("SN"),
        journal_eissn=field("EI"),
    )
    subjects = list(dict.fromkeys(split_export_list(field("WC")) + split_export_list(field("SC"))))
    doc_types = split_export_list(field("DT"))
    languages = split_export_list(field("LA"))
    isbns = [isbn for value in split_export_list(field("BN")) for isbn in find_isbns(value)]
    authors = _export_authors(raw)
    return {
        "ut": field("UT") or "",
        "doi": clean_doi(field("DI")) or clean_doi(staging_doi),
        "title": field("TI") or "(sans titre)",
        "publication_year": int(py) if (py := field("PY")) and py.isdigit() else None,
        "doc_type": doc_types[0] if doc_types else "other",
        "language": languages[0] if languages else None,
        "oa_status": None,
        "journal_title": field("SO"),
        "issn": field("SN"),
        "eissn": field("EI"),
        "publisher_name": field("PU"),
        "authors": authors,
        "authors_found": len(authors),
        "abstract": field("AB"),
        "cited_by_count": int(tc) if (tc := field("TC")) and tc.isdigit() else None,
        "biblio": biblio or None,
        "keywords": split_export_list(field("DE")) or None,
        "topics": {"subjects": subjects} if subjects else None,
        "urls": None,
        "external_ids": {ExternalIdType.ISBN: list(dict.fromkeys(isbns))} if isbns else None,
    }


def extract_record(raw: Mapping[str, JsonValue], staging_doi: str | None) -> dict[str, JsonValue]:
    """Extrait un record structuré d'un payload WoS : JSON de l'API, ou ligne d'export tabulé de l'interface (balise `UT`)."""
    if "UT" in raw:
        return extract_from_export(raw, staging_doi)
    return extract_from_api(raw, staging_doi)


# =============================================================
# PUBLISHERS & JOURNALS
# =============================================================


def upsert_publisher(publisher_name: str | None, *, publisher_store: PublisherStore) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(publisher_name, repo=publisher_store)


def get_container_facts(rec: Mapping[str, JsonValue]) -> ContainerDescription:
    """Ce que WoS dit du conteneur d'un document. Le titre de la source est la revue d'un article, le livre ou le volume d'actes d'un chapitre ou d'une communication. Sous un ISSN, le titre de la source est aussi celui de la collection : le document ne reçoit pas de monographie."""
    title = as_str(rec.get("journal_title"))
    issn, eissn = as_str(rec.get("issn")), as_str(rec.get("eissn"))
    external_ids = as_mapping(rec.get("external_ids"))
    return ContainerDescription(
        source="wos",
        raw_doc_type=as_str(rec.get("doc_type")),
        document_title=as_str(rec.get("title")),
        journal_title=title,
        collection_title=title if issn or eissn else None,
        book_title=title,
        issns=source_issns(print_issn=issn, electronic_issn=eissn),
        isbns=tuple(as_strs(external_ids.get(ExternalIdType.ISBN))),
        eisbns=tuple(as_strs(external_ids.get(ExternalIdType.EISBN))),
        year=as_int(rec.get("publication_year")),
    )


def upsert_containers(
    rec: Mapping[str, JsonValue],
    publisher_id: int | None,
    *,
    container_stores: ContainerStores,
) -> Containers:
    """Trouve ou crée la revue, ou la monographie et sa collection, qui contiennent le document."""
    return find_or_create_containers(
        get_container_facts(rec), publisher_id=publisher_id, stores=container_stores
    )


# =============================================================
# PUBLICATIONS
# =============================================================


def extract_publication_metadata(
    rec: Mapping[str, JsonValue], journal_id: int | None, monograph_id: int | None = None
) -> PublicationMetadata:
    """Extrait les métadonnées canoniques d'un record WoS.

    Cette source ne porte pas de numéro national de thèse : elle ne moissonne pas les thèses.
    """
    return PublicationMetadata(
        title=as_str(rec.get("title")),
        publication_year=as_int(rec.get("publication_year")),
        doc_type=as_str(rec.get("doc_type")),
        doi=as_str(rec.get("doi")),
        nnt=None,
        oa_status=as_str(rec.get("oa_status")),
        journal_id=journal_id,
        monograph_id=monograph_id,
        container_title=as_str(rec.get("journal_title")) if not journal_id else None,
        language=as_str(rec.get("language")),
    )


# =============================================================
# SOURCE DOCUMENTS (WOS)
# =============================================================


def insert_wos_document(
    record_store: SourceRecordStore,
    rec: Mapping[str, JsonValue],
    staging_id: int,
    publication_meta: PublicationMetadata,
) -> int:
    """Crée/retrouve l'entrée source_records pour WoS.

    Les métadonnées canoniques (doi, title, publication_year, doc_type, journal_id,
    oa_status, language, container_title) viennent toutes de `publication_meta`,
    construit en amont par `extract_publication_metadata`. `rec` ne sert ici
    que pour les extras WoS-spécifiques (abstract, cited_by_count, biblio,
    keywords, topics, urls, external_ids non canoniques).
    """
    return record_store.upsert_source_record(
        SourceRecordUpsert(
            source="wos",
            source_id=as_str(rec.get("ut")) or "",
            staging_id=staging_id,
            doi=publication_meta.doi,
            external_ids=dict(as_mapping(rec.get("external_ids"))) or None,
            title=publication_meta.title or "",
            publication_year=publication_meta.publication_year,
            raw_doc_type=publication_meta.doc_type,
            journal_id=publication_meta.journal_id,
            monograph_id=publication_meta.monograph_id,
            container_title=publication_meta.container_title,
            raw_language=publication_meta.language,
            biblio=dict(as_mapping(rec.get("biblio"))) or None,
            abstract=as_str(rec.get("abstract")),
            keywords=[k for e in as_sequence(rec.get("keywords")) if (k := as_str(e))] or None,
            topics=dict(as_mapping(rec.get("topics"))) or None,
            oa_status=publication_meta.oa_status,
            urls=[u for e in as_sequence(rec.get("urls")) if (u := as_str(e))] or None,
            impact=Impact(cited_by_count=as_int(rec.get("cited_by_count"))).to_json(),
        ),
    )


# =============================================================
# WOS CONTRIBUTIONS — identifiants sur source_contributions
# =============================================================
# Le `daisng_id` (entité algorithmique WoS non fiable) n'est pas conservé.
# Le `researcher_id` (ResearcherID Clarivate) — identifiant cross-source — figure dans les informations du contributeur (contributor_information.identifiers).


def _author_name(author: Mapping[str, JsonValue]) -> ContributorName | None:
    """`last_name` et `first_name` du payload, sinon `full_name`."""
    if as_str(author.get("last_name")):
        return ContributorName.from_parts(
            as_str(author.get("last_name")), as_str(author.get("first_name"))
        )
    return ContributorName.from_raw(as_str(author.get("full_name")))


def build_wos_author_records(
    rec: Mapping[str, JsonValue], logger: logging.Logger
) -> list[AuthorRecord]:
    """Parse les contributions d'un record WoS en `AuthorRecord` (sans I/O).

    Un record dont l'extraction a écarté tous les auteurs (`authors_found` non nul, `authors` vide) est journalisé en avertissement. Chaque auteur reçoit ses `identifiers` (researcher_id ; l'ORCID WoS n'est pas moissonné, cf. extraction), ses adresses brutes, chacune avec les ROR de ses organisations. Les `author_position` du payload WoS peuvent se répéter ; elles sont dédoublonnées ici (première occurrence gagne), la clé `(source_record_id, author_position)` interdisant les doublons en base.
    """
    authors_kept = [as_mapping(a) for a in as_sequence(rec.get("authors"))]
    if not authors_kept:
        if found := as_int(rec.get("authors_found")):
            logger.warning(
                "WoS record %s : %d auteurs présents mais aucun exploitable "
                "(filtre is_wos_author_exploitable) — contributions ignorés",
                as_str(rec.get("ut")) or "?",
                found,
            )
        return []

    ids_by_position = [
        contributor_identifiers(researcher_id=as_str(a.get("researcher_id"))) for a in authors_kept
    ]

    records: list[AuthorRecord] = []
    for idx, author in enumerate(authors_kept):
        name = _author_name(author)
        if name is None:
            continue
        ids = ids_by_position[idx]
        records.append(
            AuthorRecord(
                position=as_int(author.get("position")) or 0,
                name=name,
                is_corresponding=bool(author.get("is_corresponding")),
                roles=[
                    ContributionRole(role)
                    for e in as_sequence(author.get("roles"))
                    if (role := as_str(e))
                ]
                or None,
                identifiers=ids if ids else None,
                addresses=[
                    AddressRecord(
                        text=as_str(a.get("text")) or "",
                        ror_ids=parse_ror_ids(as_str(r) for r in as_sequence(a.get("ror_ids"))),
                    )
                    for a in (as_mapping(e) for e in as_sequence(author.get("addresses")))
                ],
            )
        )
    # `author_position` lue du payload WoS : dédup (première occurrence gagne).
    by_position: dict[int | None, AuthorRecord] = {}
    for r in records:
        by_position.setdefault(r.position, r)
    return list(by_position.values())


def extract_wos_author_block(rec: Mapping[str, JsonValue]) -> AuthorBlock:
    """Bloc auteurs d'un record WoS : `authors`, et `ut` pour le signalement d'auteurs inexploitables."""
    return {"ut": rec.get("ut"), "authors": rec.get("authors")}


def process_contributions(
    contribution_store: SourceContributionStore,
    logger: logging.Logger,
    rec: Mapping[str, JsonValue],
    source_record_id: int,
) -> None:
    """Synchronise les contributions sources WoS de l'enregistrement source depuis son bloc auteurs."""
    sync_source_contributions(
        contribution_store,
        "wos",
        source_record_id,
        extract_wos_author_block(rec),
        partial(build_wos_author_records, logger=logger),
    )


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_record(
    record_store: SourceRecordStore,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    container_stores: ContainerStores,
    publisher_store: PublisherStore,
    staging_store: StagingStore,
    contribution_store: SourceContributionStore,
) -> bool:
    """Traite un record du staging WoS. Retourne True si succès."""
    staging_id = staging_row.id
    ut = staging_row.source_id
    staging_doi = staging_row.doi
    raw_data = staging_row.raw_data

    rec = extract_record(raw_data, staging_doi)

    if not rec["ut"]:
        rec["ut"] = ut

    publisher_id = upsert_publisher(
        as_str(rec.get("publisher_name")), publisher_store=publisher_store
    )
    containers = upsert_containers(rec, publisher_id, container_stores=container_stores)
    publication_meta = extract_publication_metadata(
        rec, containers.journal_id, containers.monograph_id
    )

    source_record_id = insert_wos_document(record_store, rec, staging_id, publication_meta)
    process_contributions(contribution_store, logger, rec, source_record_id)
    staging_store.mark_done(staging_id)
    return True


class WosNormalizer(BibliographicNormalizer):
    SOURCE = "wos"
    DEFAULT_BATCH_SIZE = 500

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        rec = extract_record(row.raw_data, row.doi)
        return as_str(rec.get("title")), as_int(rec.get("publication_year"))

    def normalize_record(self, row: StagingRow) -> bool | None:
        container_stores, publisher_store = self._container_stores, self._publisher_store
        return process_record(
            self._record_store,
            self.logger,
            row,
            container_stores=container_stores,
            publisher_store=publisher_store,
            staging_store=self._staging,
            contribution_store=self._contribution_store,
        )
