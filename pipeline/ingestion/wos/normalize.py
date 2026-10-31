"""Normalisation des enregistrements sources WoS, lus dans la forme de l'API ou d'une ligne d'export tabulé."""

import logging
from collections.abc import Mapping, Sequence

from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import ContributionRole, map_role
from domain.publications.identifiers import clean_doi, find_isbns
from domain.serials.containers import ContainerDescription
from domain.serials.issns import source_issns
from domain.source_records.biblio import compact_biblio
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    isbn_role,
)
from domain.source_records.impact import Impact
from domain.structures.identifiers import parse_ror_ids
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_strs, at_path
from pipeline.ingestion.common.normalizer import Document, PublisherFacts, SourceNormalizer
from pipeline.ingestion.common.source_contributions import (
    AddressRecord,
    AuthorBlock,
    AuthorRecord,
    contributor_identifiers,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordUpsert,
)
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.wos.payload import (
    is_wos_author_usable,
    parse_export_addresses,
    parse_export_corresponding,
    parse_export_researcher_ids,
    split_export_list,
)
from pipeline.transformation.publishing.find_or_create import (
    Containers,
)


def _text_of(value: JsonValue) -> str | None:
    """Renvoie en texte une numérotation donnée par l'API en nombre ou en chaîne ; `None` si vide."""
    return str(value) if value else None


def _safe_list(obj: JsonValue) -> Sequence[JsonValue]:
    """Renvoie les valeurs d'un champ en liste : l'API renvoie parfois un objet seul à la place d'une liste."""
    if obj is None:
        return []
    if isinstance(obj, (str, Mapping)):
        return [obj]
    if isinstance(obj, Sequence):
        return obj
    return [obj]


def _get_api_title(static: Mapping[str, JsonValue], title_type: str) -> str | None:
    """Renvoie le titre d'un type donné, dans la forme de l'API."""
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
    """Lit les auteurs, dans la forme de l'API."""
    names_data = at_path(static, "summary", "names")
    name_list = _safe_list(names_data.get("name"))

    # Adresses, par numéro
    addresses_data = at_path(static, "fullrecord_metadata", "addresses")
    addr_list = _safe_list(addresses_data.get("address_name"))
    addr_map: dict[str, str] = {}  # addr_no -> full_address
    addr_orgs_map: dict[str, list[dict[str, JsonValue]]] = {}  # addr_no -> [{name, ror_id, pref}]
    for addr_entry in addr_list:
        spec = at_path(addr_entry, "address_spec")
        addr_no = spec.get("addr_no")
        if addr_no is not None:
            addr_map[str(addr_no)] = as_str(spec.get("full_address")) or ""
            # Organisations de l'adresse
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

        # L'ORCID WoS (`PreferredORCID`) est ignoré : attribué par le matching interne de Web of Science, il est trop peu fiable pour les informations du contributeur.
        # Les ORCID fiables viennent des sources où l'auteur les dépose (`ORCID_MATCH_SOURCES`).

        is_corresponding = as_str(name_obj.get("reprint")) == "Y"

        # Affiliations, par numéro d'adresse
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
    """Renvoie le DOI, dans la forme de l'API."""
    try:
        identifiers = at_path(dynamic, "cluster_related", "identifiers").get("identifier", [])
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == "doi":
                return clean_doi(str(ident.get("value", "")))
    except KeyError, TypeError:
        pass
    return None


def _get_api_issn(dynamic: Mapping[str, JsonValue], issn_type: str = "issn") -> str | None:
    """Renvoie l'ISSN ou l'eISSN, dans la forme de l'API."""
    try:
        identifiers = at_path(dynamic, "cluster_related", "identifiers").get("identifier", [])
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == issn_type:
                return str(ident.get("value", "")).strip() or None
    except KeyError, TypeError:
        pass
    return None


def _get_api_isbns(dynamic: Mapping[str, JsonValue], isbn_type: str) -> list[str]:
    """Renvoie les ISBN d'un support (`isbn` papier, `eisbn` électronique), distingués par WoS selon le type de l'identifiant."""
    identifiers = at_path(dynamic, "cluster_related", "identifiers").get("identifier", [])
    isbns: list[str] = []
    for entry in _safe_list(identifiers):
        ident = as_mapping(entry)
        if as_str(ident.get("type")) == isbn_type:
            isbns += find_isbns(as_str(ident.get("value")))
    return list(dict.fromkeys(isbns))


def extract_from_api(raw: Mapping[str, JsonValue], staging_doi: str | None) -> dict[str, JsonValue]:  # noqa: C901
    """Lit le record structuré d'un payload de l'API."""
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

    doctypes = at_path(summary, "doctypes")
    doctype_list = _safe_list(doctypes.get("doctype"))
    raw_doc_type = None
    if doctype_list:
        first = doctype_list[0]
        raw_doc_type = as_str(as_mapping(first).get("content")) or as_str(first)

    publishers = at_path(summary, "publishers")
    publisher_data = at_path(publishers, "publisher")
    publisher_names = at_path(publisher_data, "names")
    names = _safe_list(publisher_names.get("name"))
    publisher_name_obj = as_mapping(names[0]) if names else {}
    publisher_name = as_str(publisher_name_obj.get("unified_name")) or as_str(
        publisher_name_obj.get("full_name")
    )

    journal_title = _get_api_title(static, "source")

    lang_data = at_path(static, "fullrecord_metadata", "languages")
    lang_list = _safe_list(lang_data.get("language"))
    language = None
    if lang_list:
        language = as_str(as_mapping(lang_list[0]).get("content")) or as_str(lang_list[0])

    # Numérotation et éditeur nommés par WoS.
    page = at_path(publication_info, "page")
    biblio = compact_biblio(
        volume=_text_of(publication_info.get("vol")),
        issue=_text_of(publication_info.get("issue")),
        first_page=_text_of(page.get("begin")),
        last_page=_text_of(page.get("end")),
        publisher=publisher_name,
    )

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

    # Web of Science renvoie un mot-clé unique en chaîne, plusieurs en liste.
    kw_raw = at_path(frm, "keywords").get("keyword", [])
    single_word = as_str(kw_raw)
    keywords = ([single_word] if single_word else as_strs(kw_raw)) or None

    # Topics : catégories WoS.
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
        "journal_title": journal_title,
        "issn": _get_api_issn(dynamic, "issn"),
        "eissn": _get_api_issn(dynamic, "eissn"),
        "publisher_name": publisher_name,
        "authors": [a for a in authors if is_wos_author_usable(a)],
        "authors_found": len(authors),
        "abstract": abstract,
        "cited_by_count": cited_by_count,
        "biblio": biblio or None,
        "keywords": keywords,
        "topics": topics or None,
        "urls": None,
        "isbns": _get_api_isbns(dynamic, "isbn"),
        "eisbns": _get_api_isbns(dynamic, "eisbn"),
    }


def _export_authors(raw: Mapping[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Lit les auteurs d'une ligne d'export, dans l'ordre de `AF` (noms complets) et `AU` (noms abrégés)."""
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
    """Lit le record structuré d'une ligne d'export tabulé de l'interface WoS, sous la même forme qu'`extract_from_api`. Le statut open access reste inconnu."""

    def field(tag: str) -> str | None:
        return as_str(raw.get(tag))

    biblio = compact_biblio(
        volume=field("VL"),
        issue=field("IS"),
        first_page=field("BP"),
        last_page=field("EP"),
        publisher=field("PU"),
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
        "isbns": list(dict.fromkeys(isbns)),
        "eisbns": [],
    }


def extract_record(raw: Mapping[str, JsonValue], staging_doi: str | None) -> dict[str, JsonValue]:
    """Lit le record structuré d'un payload WoS : JSON de l'API, ou ligne d'export tabulé de l'interface (balise `UT`)."""
    if "UT" in raw:
        return extract_from_export(raw, staging_doi)
    return extract_from_api(raw, staging_doi)


def get_container_facts(rec: Mapping[str, JsonValue]) -> ContainerDescription:
    """Décrit le conteneur d'un document d'après WoS.

    Le titre de la source est la revue d'un article, le livre ou le volume d'actes d'un chapitre ou d'une communication. Sous un ISSN, le titre de la source est aussi celui de la collection : le document reste sans monographie.
    """
    title = as_str(rec.get("journal_title"))
    issn, eissn = as_str(rec.get("issn")), as_str(rec.get("eissn"))
    return ContainerDescription(
        source="wos",
        raw_doc_type=as_str(rec.get("doc_type")),
        document_title=as_str(rec.get("title")),
        journal_title=title,
        collection_title=title if issn or eissn else None,
        book_title=title,
        issns=source_issns(print_issn=issn, electronic_issn=eissn),
        isbns=tuple(as_strs(rec.get("isbns"))),
        eisbns=tuple(as_strs(rec.get("eisbns"))),
        year=as_int(rec.get("publication_year")),
    )


def wos_identifiers(rec: Mapping[str, JsonValue]) -> tuple[SourceIdentifier, ...]:
    """Renvoie les identifiants d'un record WoS. Le DOI est secondaire, le rôle des ISBN suit le type du record (`isbn_role`)."""
    role = isbn_role(as_str(rec.get("doc_type")), "wos")
    identifiers: list[SourceIdentifier] = []
    if doi := as_str(rec.get("doi")):
        identifiers.append(
            SourceIdentifier(SourceIdentifierType.DOI, doi, SourceIdentifierRole.SECONDARY)
        )
    for id_type, key in (
        (SourceIdentifierType.ISBN, "isbns"),
        (SourceIdentifierType.EISBN, "eisbns"),
    ):
        identifiers += (SourceIdentifier(id_type, isbn, role) for isbn in as_strs(rec.get(key)))
    return tuple(identifiers)


def wos_source_record(
    rec: Mapping[str, JsonValue], staging_id: int, containers: Containers
) -> SourceRecordUpsert:
    """Construit l'enregistrement source WoS d'un record, identifié par son UT.

    Le titre de la source sert de titre libre du conteneur à défaut de revue. Les records WoS sont sans NNT.
    """
    return SourceRecordUpsert(
        source="wos",
        source_id=as_str(rec.get("ut")) or "",
        staging_id=staging_id,
        identifiers=wos_identifiers(rec),
        title=as_str(rec.get("title")) or "",
        publication_year=as_int(rec.get("publication_year")),
        raw_doc_type=as_str(rec.get("doc_type")),
        serial_id=containers.serial_id,
        monograph_id=containers.monograph_id,
        container_title=as_str(rec.get("journal_title")) if not containers.serial_id else None,
        raw_language=as_str(rec.get("language")),
        biblio=dict(as_mapping(rec.get("biblio"))) or None,
        abstract=as_str(rec.get("abstract")),
        keywords=[k for e in as_sequence(rec.get("keywords")) if (k := as_str(e))] or None,
        topics=dict(as_mapping(rec.get("topics"))) or None,
        urls=[u for e in as_sequence(rec.get("urls")) if (u := as_str(e))] or None,
        impact=Impact(cited_by_count=as_int(rec.get("cited_by_count"))).to_json(),
    )


# Le `daisng_id`, entité calculée par WoS et peu fiable, reste hors de la base.
# Le `researcher_id` (ResearcherID de Clarivate), identifiant commun à plusieurs sources, va dans les informations du contributeur.


def _author_name(author: Mapping[str, JsonValue]) -> ContributorName | None:
    """Lit le nom de l'auteur : `last_name` et `first_name` du payload, sinon `full_name`."""
    if as_str(author.get("last_name")):
        return ContributorName.from_parts(
            as_str(author.get("last_name")), as_str(author.get("first_name"))
        )
    return ContributorName.from_raw(as_str(author.get("full_name")))


def build_wos_author_records(
    rec: Mapping[str, JsonValue], logger: logging.Logger
) -> list[AuthorRecord]:
    """Lit les contributions sources d'un record WoS.

    Un record aux auteurs tous écartés par la lecture du payload est journalisé en avertissement. Chaque auteur reçoit son ResearcherID et ses adresses, chacune avec les ROR de ses organisations. Les positions du payload WoS peuvent se répéter ; la base interdit deux contributions sources de même position : la première occurrence l'emporte.
    """
    authors_kept = [as_mapping(a) for a in as_sequence(rec.get("authors"))]
    if not authors_kept:
        if found := as_int(rec.get("authors_found")):
            logger.warning(
                "WoS record %s : %d auteurs présents mais aucun exploitable "
                "(filtre is_wos_author_usable), contributions ignorées",
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
    # Positions lues du payload : la première occurrence l'emporte.
    by_position: dict[int | None, AuthorRecord] = {}
    for r in records:
        by_position.setdefault(r.position, r)
    return list(by_position.values())


def extract_wos_author_block(rec: Mapping[str, JsonValue]) -> AuthorBlock:
    """Renvoie le bloc auteurs d'un record WoS : `authors`, et `ut` pour le signalement d'auteurs inexploitables."""
    return {"ut": rec.get("ut"), "authors": rec.get("authors")}


class WosNormalizer(SourceNormalizer):
    SOURCE = "wos"
    DEFAULT_BATCH_SIZE = 500

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        rec = extract_record(row.raw_data, row.doi)
        return as_str(rec.get("title")), as_int(rec.get("publication_year"))

    def parse(self, row: StagingRow) -> Document:
        """Lit le record dans la forme de l'API ou de l'export. Un record sans UT prend l'identifiant de sa ligne de `staging`."""
        rec = extract_record(row.raw_data, row.doi)
        if not rec["ut"]:
            rec["ut"] = row.source_id
        return rec

    def publisher(self, doc: Document) -> PublisherFacts | None:
        name = as_str(doc.get("publisher_name"))
        return PublisherFacts(name) if name else None

    def container_facts(self, doc: Document) -> ContainerDescription:
        return get_container_facts(doc)

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        return wos_source_record(doc, row.id, containers)

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_wos_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_wos_author_records(block, self.logger)
