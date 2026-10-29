"""Normalisation des enregistrements sources HAL."""

from collections.abc import Mapping
from datetime import date
from functools import lru_cache
from typing import cast
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from domain.dates import today
from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import map_role
from domain.publications.doc_types import DocType
from domain.publications.identifiers import (
    clean_doi,
    find_isbns,
    normalize_arxiv_id,
    normalize_nnt,
    normalize_pmcid,
    normalize_pmid,
)
from domain.publications.licenses import normalize_license
from domain.serials.containers import ContainerDescription
from domain.serials.issns import source_issns
from domain.source_records.biblio import PageRange, compact_biblio, parse_pages
from domain.source_records.doc_types import map_doc_type
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    isbn_role,
)
from domain.structures.identifiers import parse_ror_ids
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_strs
from pipeline.ingestion.common.locations import LocationFacts
from pipeline.ingestion.common.normalizer import Document, PublisherFacts, SourceNormalizer
from pipeline.ingestion.common.source_contributions import (
    AuthorBlock,
    AuthorRecord,
    contributor_identifiers,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordUpsert,
)
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.hal.payload import (
    derive_hal_oa_status,
    extract_hal_source_extras,
    hal_text_field,
)
from pipeline.transformation.publishing.find_or_create import (
    Containers,
)


def get_title(doc: Mapping[str, JsonValue]) -> str:
    """Titre du dépôt."""
    return hal_text_field(doc.get("title_s")) or hal_text_field(doc.get("label_s")) or ""


def get_container_facts(doc: Mapping[str, JsonValue]) -> ContainerDescription:
    """Ce que HAL dit du conteneur d'un document : la revue ou la collection (`journalTitle_s`), le livre ou le volume d'actes (`bookTitle_s`), et les ISBN du TEI.

    Une communication cite presque toujours le congrès (`conferenceTitle_s`), avec ou sans actes publiés : seul, le congrès désigne un événement. Quand le dépôt a un ISBN, le volume existe : il prend le titre de la source (`source_s`), à défaut celui du congrès.
    """
    journal_title = hal_text_field(doc.get("journalTitle_s"))
    isbns = tuple(parse_tei_isbns(hal_text_field(doc.get("label_xml"))))
    book_title = hal_text_field(doc.get("bookTitle_s"))
    if not book_title and isbns:
        book_title = hal_text_field(doc.get("source_s")) or hal_text_field(
            doc.get("conferenceTitle_s")
        )
    return ContainerDescription(
        source="hal",
        raw_doc_type=hal_text_field(doc.get("docType_s")),
        document_title=get_title(doc),
        journal_title=journal_title,
        collection_title=journal_title,
        book_title=book_title,
        issns=source_issns(
            print_issn=hal_text_field(doc.get("journalIssn_s")),
            electronic_issn=hal_text_field(doc.get("journalEissn_s")),
        ),
        isbns=isbns,
        year=as_int(doc.get("producedDateY_i")),
    )


def get_doc_type(doc: Mapping[str, JsonValue]) -> str | None:
    """Type brut HAL : `docType_s`, suivi de `docSubType_s` quand HAL en donne un (ex. `ART_review-article`)."""
    raw_type = hal_text_field(doc.get("docType_s")) or ""
    raw_sub = hal_text_field(doc.get("docSubType_s")) or ""
    return f"{raw_type}_{raw_sub}" if raw_sub else raw_type or None


def get_container_title(doc: Mapping[str, JsonValue]) -> str | None:
    """Titre du livre, du congrès ou de la revue, dans cet ordre."""
    return (
        hal_text_field(doc.get("bookTitle_s"))
        or hal_text_field(doc.get("conferenceTitle_s"))
        or hal_text_field(doc.get("journalTitle_s"))
    )


def get_oa_status(doc: Mapping[str, JsonValue], embargo_until: date | None) -> str | None:
    """Statut open access tiré de `openAccess_bool`, du fichier déposé, du lien externe et de l'embargo actif."""
    is_open = doc.get("openAccess_bool")
    return derive_hal_oa_status(
        is_open if isinstance(is_open, bool) else None,
        hal_text_field(doc.get("fileMain_s")),
        hal_text_field(doc.get("linkExtId_s")),
        embargo_until,
    )


def get_locations(doc: Mapping[str, JsonValue], embargo_until: date | None) -> list[LocationFacts]:
    """La page du dépôt HAL (`uri_s`), avec le fichier déposé (`fileMain_s`) et sa licence. La copie est ouverte quand un fichier est déposé, hors embargo actif (`embargo_until`). Une copie sous embargo s'ouvre quand elle est renormalisée après la levée."""
    uri = hal_text_field(doc.get("uri_s"))
    if not uri:
        return []
    file_main = hal_text_field(doc.get("fileMain_s"))
    return [
        LocationFacts(
            url=uri,
            pdf_url=file_main,
            license=normalize_license(hal_text_field(doc.get("licence_s"))),
            is_oa=file_main is not None and embargo_until is None,
        )
    ]


_BOOK_TYPES = frozenset({DocType.BOOK, DocType.BOOK_CHAPTER})


def page_range(page_s: str | None, raw_doc_type: str | None) -> PageRange:
    """Pagination HAL (`page_s`). Sur un livre ou un chapitre, un nombre seul est le nombre de pages de l'ouvrage : il est écarté."""
    if (page_s or "").strip().isdigit() and map_doc_type(raw_doc_type or "", "hal") in _BOOK_TYPES:
        return PageRange()
    return parse_pages(page_s)


def build_hal_identifiers(
    doc: Mapping[str, JsonValue], hal_id: str, nnt: str | None
) -> tuple[SourceIdentifier, ...]:
    """Identifiants d'un dépôt HAL. Le `hal_id` est primaire, les autres sont secondaires, sauf l'ISBN de l'ouvrage qui contient le document (`isbn_role`).

    Le PMID vient de `pubmedId_s`, les PMCID et identifiants arXiv des liens externes (`linkExtUrl_s`).
    """
    secondary = SourceIdentifierRole.SECONDARY
    identifiers = [
        SourceIdentifier(SourceIdentifierType.HAL_ID, hal_id, SourceIdentifierRole.PRIMARY)
    ]
    if doi := clean_doi(hal_text_field(doc.get("doiId_s"))):
        identifiers.append(SourceIdentifier(SourceIdentifierType.DOI, doi, secondary))
    if nnt:
        identifiers.append(SourceIdentifier(SourceIdentifierType.NNT, nnt, secondary))
    role = isbn_role(get_doc_type(doc), "hal")
    identifiers += (
        SourceIdentifier(SourceIdentifierType.ISBN, isbn, role)
        for isbn in parse_tei_isbns(hal_text_field(doc.get("label_xml")))
    )
    if pmid := normalize_pmid(hal_text_field(doc.get("pubmedId_s"))):
        identifiers.append(SourceIdentifier(SourceIdentifierType.PMID, pmid, secondary))
    raw = doc.get("linkExtUrl_s")
    link_urls = [raw] if isinstance(raw, str) else as_sequence(raw)
    for entry in link_urls:
        url = hal_text_field(entry)
        if pmcid := normalize_pmcid(url):
            identifiers.append(SourceIdentifier(SourceIdentifierType.PMCID, pmcid, secondary))
        if arxiv_id := normalize_arxiv_id(url):
            identifiers.append(SourceIdentifier(SourceIdentifierType.ARXIV_ID, arxiv_id, secondary))
    return tuple(identifiers)


def hal_source_record(
    doc: Mapping[str, JsonValue],
    staging_id: int,
    hal_id: str,
    containers: Containers,
) -> SourceRecordUpsert:
    """Enregistrement source HAL d'un dépôt, identifié par son `hal_id`.

    Le titre libre du conteneur se pose seulement sans revue.
    """
    doc_type = get_doc_type(doc)
    nnt = normalize_nnt(hal_text_field(doc.get("nntId_s")))
    embargo_until = active_embargo_until(hal_text_field(doc.get("label_xml")), today())

    # Toutes les collections du dépôt.
    collections_array = sorted(set(as_strs(doc.get("collCode_s")))) or None

    # Abstract
    abstract = hal_text_field(doc.get("abstract_s"))

    # Keywords
    keywords = list(dict.fromkeys(as_strs(doc.get("keyword_s")))) or None

    # Topics : domaines HAL, stockés tels que la source les expose (code + chemin de libellés).
    domain_raw = doc.get("fr_domainAllCodeLabel_fs")
    topics = {"hal_domains": domain_raw} if isinstance(domain_raw, list) and domain_raw else None

    # Éditeur et revue tels que HAL les nomme.
    biblio_json = compact_biblio(
        volume=hal_text_field(doc.get("volume_s")),
        issue=hal_text_field(doc.get("issue_s")),
        **page_range(hal_text_field(doc.get("page_s")), doc_type)._asdict(),
        publisher=hal_text_field(doc.get("journalPublisher_s"))
        or hal_text_field(doc.get("publisher_s")),
        journal_title=hal_text_field(doc.get("journalTitle_s")),
        journal_issn=hal_text_field(doc.get("journalIssn_s")),
        journal_eissn=hal_text_field(doc.get("journalEissn_s")),
    )

    # URLs
    uri = hal_text_field(doc.get("uri_s"))
    urls = [uri] if uri else None

    return SourceRecordUpsert(
        source="hal",
        source_id=hal_id,
        staging_id=staging_id,
        doi=clean_doi(hal_text_field(doc.get("doiId_s"))),
        identifiers=build_hal_identifiers(doc, hal_id, nnt),
        title=get_title(doc),
        publication_year=as_int(doc.get("producedDateY_i")),
        raw_doc_type=doc_type,
        serial_id=containers.serial_id,
        monograph_id=containers.monograph_id,
        container_title=get_container_title(doc) if not containers.serial_id else None,
        raw_language=hal_text_field(doc.get("language_s")),
        biblio=biblio_json,
        source_extras=extract_hal_source_extras(doc),
        abstract=abstract,
        keywords=keywords,
        topics=topics,
        oa_status=get_oa_status(doc, embargo_until),
        license=normalize_license(hal_text_field(doc.get("licence_s"))),
        urls=urls,
        embargo_until=embargo_until,
        hal_collections=collections_array,
    )


_TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@lru_cache(maxsize=1)
def _parse_tei(label_xml: str) -> Element:
    """Lit le TEI joint à un dépôt HAL.

    Le cache garde l'arbre du dernier dépôt : les lecteurs du TEI (ISBN, embargo, identifiants d'auteurs) reçoivent la même chaîne pendant la normalisation d'un dépôt, et partagent une seule analyse. Ils ne modifient pas l'arbre.

    L'analyseur refuse les déclarations de type de document et d'entités, que l'analyseur de la bibliothèque standard développe : quelques centaines d'octets y suffisent à en produire des milliards. Lève `ParseError` sur un document mal formé, une sous-classe de `DefusedXmlException` sur un document qui en contient.
    """
    return cast("Element", ET.fromstring(label_xml))


def active_embargo_until(label_xml: str | None, today: date) -> date | None:
    """Date de fin d'un embargo HAL encore actif, sinon `None`.

    Lit `ref[@type='file']/date/@notBefore` du TEI : la date à laquelle le fichier déposé devient accessible. Parmi plusieurs `ref` de type `file` (page et document), la plus tardive l'emporte. Une date échue rend `None` : un embargo levé reste hors de la base. À l'échéance d'un embargo stocké, une règle de correction de `oa_status` le lève, sans nouvel import HAL.
    """
    if not label_xml:
        return None
    try:
        root = _parse_tei(label_xml)
    except ParseError, DefusedXmlException:
        return None
    dates: list[date] = []
    for ref in root.iter(f"{{{_TEI_NS['tei']}}}ref"):
        if ref.get("type") != "file":
            continue
        date_el = ref.find("tei:date", _TEI_NS)
        if date_el is None:
            continue
        not_before = date_el.get("notBefore")
        if not_before:
            try:
                dates.append(date.fromisoformat(not_before))
            except ValueError:
                continue
    if not dates:
        return None
    latest = max(dates)
    return latest if latest > today else None


def parse_tei_isbns(label_xml: str | None) -> list[str]:
    """ISBN du TEI HAL (`idno[@type='isbn']`), seul endroit où HAL les donne.

    Une zone contient parfois deux ISBN, un EAN qui répète l'ISBN, ou un numéro de chapitre à la suite : `find_isbns` en tire les ISBN valides.
    """
    if not label_xml:
        return []
    try:
        root = _parse_tei(label_xml)
    except ParseError, DefusedXmlException:
        return []
    isbns: list[str] = []
    for idno in root.iter(f"{{{_TEI_NS['tei']}}}idno"):
        if idno.get("type") != "isbn":
            continue
        isbns += [isbn for isbn in find_isbns(idno.text) if isbn not in isbns]
    return isbns


def _tei_root(label_xml: str | None) -> Element | None:
    """Racine du TEI. `None` si `label_xml` est absent ou mal formé."""
    if not label_xml:
        return None
    try:
        return _parse_tei(label_xml)
    except ParseError, DefusedXmlException:
        return None


def _title_authors(root: Element | None) -> list[Element]:
    """Éléments `author` du `titleStmt` TEI, dans l'ordre des auteurs."""
    title_stmt = None if root is None else root.find(".//tei:biblFull/tei:titleStmt", _TEI_NS)
    return [] if title_stmt is None else title_stmt.findall("tei:author", _TEI_NS)


def _tei_title_authors(label_xml: str | None) -> list[Element]:
    """Éléments `author` du `titleStmt` TEI, dans l'ordre des auteurs. Liste vide si `label_xml` est absent ou mal formé."""
    return _title_authors(_tei_root(label_xml))


def parse_tei_author_names(label_xml: str | None) -> list[list[str]]:
    """`[surname, forename]` de chaque auteur du TEI HAL, dans l'ordre des auteurs. Un champ absent vaut `""`."""
    out: list[list[str]] = []
    for author in _tei_title_authors(label_xml):
        pers = author.find("tei:persName", _TEI_NS)
        out.append(
            [
                " ".join((e.text or "").strip() for e in pers.findall(f"tei:{part}", _TEI_NS))
                if pers is not None
                else ""
                for part in ("surname", "forename")
            ]
        )
    return out


def parse_tei_author_identifiers(label_xml: str | None) -> list[dict[str, str]]:
    """ORCID, IdRef et idHAL de chaque auteur du TEI HAL, dans l'ordre des auteurs.

    Le TEI est le seul champ qui rattache chaque identifiant à son auteur : les listes Solr `authORCIDIdExt_s` et `authIdRefIdExt_s` omettent les valeurs nulles et perdent l'alignement. Liste vide si `label_xml` est absent ou mal formé.
    """
    out: list[dict[str, str]] = []
    for author in _tei_title_authors(label_xml):
        ids: dict[str, str] = {}
        for idno in author.findall("tei:idno", _TEI_NS):
            typ = (idno.get("type") or "").upper()
            notation = (idno.get("notation") or "").lower()
            val = (idno.text or "").strip()
            if not val:
                continue
            if typ == "ORCID":
                ids["orcid"] = val
            elif typ == "IDREF":
                ids["idref"] = val
            elif typ == "IDHAL":
                # HAL donne souvent deux <idno type="idhal"> par auteur : notation="string", le slug `prenom-nom`, qui est l'idHAL, et notation="numeric", le hal_person_id réétiqueté.
                # Seul le slug compte ici ; le hal_person_id vient du champ composite Solr.
                if notation != "string":
                    continue
                ids["idhal"] = val
        out.append(ids)
    return out


_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def parse_tei_author_rors(label_xml: str | None) -> list[list[str]]:
    """ROR des structures d'affiliation de chaque auteur du TEI HAL, dans l'ordre des auteurs.

    Un auteur désigne ses structures par `affiliation/@ref` (`#struct-<identifiant>`) ; le ROR d'une structure est son `idno` de type `ROR` dans `listOrg`.
    """
    root = _tei_root(label_xml)
    if root is None:
        return []
    ror_by_struct: dict[str, str] = {}
    for org in root.iterfind(".//tei:listOrg/tei:org", _TEI_NS):
        struct = org.get(_XML_ID)
        for idno in org.findall("tei:idno", _TEI_NS):
            if struct and (idno.get("type") or "").upper() == "ROR" and (idno.text or "").strip():
                ror_by_struct[struct] = (idno.text or "").strip()
    return [
        [
            ror_by_struct[ref]
            for aff in author.findall("tei:affiliation", _TEI_NS)
            if (ref := (aff.get("ref") or "").removeprefix("#")) in ror_by_struct
        ]
        for author in _title_authors(root)
    ]


def parse_tei_author_structures(label_xml: str | None) -> list[list[int]]:
    """Structures HAL directes de chaque auteur du TEI HAL, dans l'ordre des auteurs : identifiants de `affiliation/@ref` (`#struct-<identifiant>`)."""
    root = _tei_root(label_xml)
    if root is None:
        return []
    return [
        sorted(
            {
                int(ref)
                for aff in author.findall("tei:affiliation", _TEI_NS)
                if (ref := (aff.get("ref") or "").removeprefix("#struct-")).isdigit()
            }
        )
        for author in _title_authors(root)
    ]


_HAL_AUTHOR_FIELDS = (
    "authFullNameFormIDPersonIDIDHal_fs",
    "authQuality_s",
)


def extract_hal_author_block(doc: Mapping[str, JsonValue]) -> AuthorBlock:
    """Bloc auteurs d'un document HAL : les champs Solr des auteurs, et les identifiants, noms, ROR et structures par auteur extraits du TEI (`tei_author_identifiers`, `tei_author_names`, `tei_author_rors`, `tei_author_structures`)."""
    label_xml = hal_text_field(doc.get("label_xml"))
    block: dict[str, JsonValue] = {field: doc.get(field) for field in _HAL_AUTHOR_FIELDS}
    block["tei_author_identifiers"] = cast("JsonValue", parse_tei_author_identifiers(label_xml))
    block["tei_author_names"] = cast("JsonValue", parse_tei_author_names(label_xml))
    block["tei_author_rors"] = cast("JsonValue", parse_tei_author_rors(label_xml))
    block["tei_author_structures"] = cast("JsonValue", parse_tei_author_structures(label_xml))
    return block


def build_hal_author_records(doc: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Contributions sources d'un dépôt HAL.

    Les champs Solr alignés donnent le nom, le rôle et le `hal_person_id` de chaque auteur. Le TEI donne ses identifiants (ORCID, IdRef, idHAL), ses nom et prénom, ses structures directes (`hal_structure_ids`) et leurs ROR (`ror_ids`). HAL donne des structures de son référentiel, sans texte d'affiliation : les contributions sources sont sans adresse.
    """
    qualities = [hal_text_field(q) for q in as_sequence(doc.get("authQuality_s"))]
    # ORCID, IdRef et idHAL par auteur, extraits du TEI : seul champ HAL qui les attache proprement à chaque position d'auteur.
    tei_ids = [as_mapping(e) for e in as_sequence(doc.get("tei_author_identifiers"))]
    # Nom et prénom séparés par auteur, extraits du TEI ; à défaut, le nom Solr.
    tei_names = [
        [as_str(p) for p in as_sequence(e)] for e in as_sequence(doc.get("tei_author_names"))
    ]
    # ROR des structures d'affiliation, par auteur.
    tei_rors = [
        parse_ror_ids(as_str(r) for r in as_sequence(e))
        for e in as_sequence(doc.get("tei_author_rors"))
    ]
    # Structures HAL directes, par auteur.
    tei_structures = [
        frozenset(int(i) for i in as_sequence(e) if isinstance(i, int))
        for e in as_sequence(doc.get("tei_author_structures"))
    ]

    # `authFullNameFormIDPersonIDIDHal_fs` : « Nom_FacetSep_formId-personId_FacetSep_idhal », aligné par position. L'appelant en vérifie la présence.
    # Le troisième segment (idhal) reste inutilisé : pour un auteur sans slug, HAL y recopie le person_id numérique. L'idHAL vient du seul TEI (`parse_tei_author_identifiers`).
    composite = [
        entry
        for e in as_sequence(doc.get("authFullNameFormIDPersonIDIDHal_fs"))
        if (entry := hal_text_field(e))
    ]
    names = [entry.split("_FacetSep_", 1)[0] for entry in composite]
    hal_person_id_by_pos: dict[int, int | None] = {}

    for pos, entry in enumerate(composite):
        parts = entry.split("_FacetSep_")
        if len(parts) >= 2:
            # parts[1] = "formId-personId"
            dash_parts = parts[1].rsplit("-", 1)
            if len(dash_parts) == 2:
                try:
                    pid = int(dash_parts[1])
                    if pid > 0:  # 0 = personne non identifiée par HAL
                        hal_person_id_by_pos[pos] = pid
                except ValueError:
                    pass

    ids_by_position = [
        contributor_identifiers(
            orcid=(as_str(tei_ids[pos].get("orcid")) if pos < len(tei_ids) else None),
            idref=(as_str(tei_ids[pos].get("idref")) if pos < len(tei_ids) else None),
            idhal=(as_str(tei_ids[pos].get("idhal")) if pos < len(tei_ids) else None),
            hal_person_id=hal_person_id_by_pos.get(pos),
        )
        for pos in range(len(names))
    ]

    records: list[AuthorRecord] = []
    for position, name in enumerate(names):
        # authQuality_s : rôle de l'auteur (aut, crp, dir, edt, …)
        quality = qualities[position] if position < len(qualities) else None
        roles, is_corresponding_from_role = map_role("hal", quality)
        is_corresponding = is_corresponding_from_role

        if not name:
            continue
        contributor_name = (
            ContributorName.from_parts(*tei_names[position][:2])
            if position < len(tei_names)
            and len(tei_names[position]) >= 2
            and tei_names[position][0]
            else ContributorName.from_raw(name)
        )
        if contributor_name is None:
            continue

        identifiers = ids_by_position[position]

        records.append(
            AuthorRecord(
                position=position,
                name=contributor_name,
                is_corresponding=is_corresponding,
                roles=roles or None,
                identifiers=identifiers,
                ror_ids=tei_rors[position] if position < len(tei_rors) else frozenset(),
                hal_structure_ids=(
                    tei_structures[position] if position < len(tei_structures) else frozenset()
                ),
            )
        )

    return records


class HalNormalizer(SourceNormalizer):
    SOURCE = "hal"
    DEFAULT_BATCH_SIZE = 500

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return get_title(row.raw_data), as_int(row.raw_data.get("producedDateY_i"))

    def parse(self, row: StagingRow) -> Document | None:
        """Le dépôt, refusé sans champ auteurs."""
        return row.raw_data if row.raw_data.get("authFullNameFormIDPersonIDIDHal_fs") else None

    def publisher(self, doc: Document) -> PublisherFacts | None:
        name = hal_text_field(doc.get("journalPublisher_s")) or hal_text_field(
            doc.get("publisher_s")
        )
        return PublisherFacts(name) if name else None

    def container_facts(self, doc: Document) -> ContainerDescription:
        return get_container_facts(doc)

    def locations(self, doc: Document) -> list[LocationFacts]:
        return get_locations(
            doc, active_embargo_until(hal_text_field(doc.get("label_xml")), today())
        )

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        return hal_source_record(doc, row.id, row.source_id, containers)

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_hal_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_hal_author_records(block)
