"""Normalisation des données DataCite : staging → tables structurées.

Particularités DataCite :
- Le staging stocke le nœud JSON:API `data` ; les métadonnées sont dans `data.attributes`.
- `creators` : nom + ORCID éventuel (`nameIdentifiers` scheme ORCID) + affiliations textuelles. Les creators `Organizational` donnent des contributions sources collectives. Affiliations routées vers `addresses` via le writer batch partagé, comme HAL / OpenAlex / CrossRef.
- `raw_doc_type` : token brut issu de `types` (cf. `pipeline.ingestion.datacite.payload.extract_datacite_doc_type_token`).
- `relatedIdentifiers` (type DOI) → `external_ids.related_dois` (recherche par DOI + relations) et `source_extras.related_identifiers` (avec `relationType`, pour la résolution concept/version et les relations entre publications).
- `oa_status` non dérivé de DataCite ; laissé à NULL pour arbitrage aval.
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.dates import today
from domain.persons.contributor_name import ContributorName
from domain.persons.identifiers import normalize_orcid
from domain.publications.contribution_roles import ContributionRole
from domain.publications.identifiers import clean_doi
from domain.publications.licenses import datacite_license
from domain.serials.containers import ContainerDescription
from domain.serials.issns import source_issns
from domain.source_records.biblio import compact_biblio
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.impact import Impact
from domain.structures.identifiers import RorId, parse_ror_ids
from domain.types import JsonValue, as_mapping, as_sequence, as_str, as_text
from domain.urls import is_host
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
from pipeline.ingestion.datacite.payload import (
    container_names_a_journal,
    extract_datacite_doc_type_token,
    extract_datacite_publication_year,
    extract_datacite_source_extras,
    extract_related_dois,
    get_abstract,
    get_cited_by_count,
    get_container,
    get_container_pages,
    get_isbns,
    get_keywords,
    get_language,
    get_publisher_name,
    get_title,
)
from pipeline.transformation.publishing.find_or_create import (
    Containers,
)

# =============================================================
# PUBLISHER + JOURNAL
# =============================================================


def get_container_facts(attributes: Mapping[str, JsonValue]) -> ContainerDescription:
    """Ce que DataCite dit du conteneur d'un document.

    Le `container` compte seulement quand il désigne celui qui publie le document (`container_names_a_journal`) : son titre est alors la revue d'un article, la collection quand un ISSN l'identifie, le livre ou le volume d'actes sinon. Un livre garde son propre titre et ses ISBN, et un chapitre l'ISBN de son livre, même sans conteneur.
    """
    title, issn = get_container(attributes)
    doc_type = extract_datacite_doc_type_token(attributes)
    if not (title and container_names_a_journal(doc_type, title, get_container_pages(attributes))):
        title = issn = None
    return ContainerDescription(
        source="datacite",
        raw_doc_type=doc_type,
        document_title=get_title(attributes),
        journal_title=title,
        collection_title=title if issn else None,
        book_title=None if issn else title,
        issns=source_issns(unknown=[issn]),
        isbns=tuple(get_isbns(attributes)),
        year=extract_datacite_publication_year(attributes, max_year=today().year + 1),
    )


def get_biblio(attributes: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Volume / issue / pages depuis `container` + publisher/journal bruts.

    Trace le nom de l'éditeur et de la revue tels que vus par DataCite, en parallèle des publishers/serials créés via `find_or_create_*`.
    """
    container = as_mapping(attributes.get("container"))
    title, issn = get_container(attributes)
    return compact_biblio(
        volume=as_text(container.get("volume")),
        issue=as_text(container.get("issue")),
        first_page=as_text(container.get("firstPage")),
        last_page=as_text(container.get("lastPage")),
        publisher=get_publisher_name(attributes),
        journal_title=title,
        journal_issn=issn,
    )


# =============================================================
# AUTEURS
# =============================================================


def _creator_name(creator: Mapping[str, JsonValue]) -> ContributorName | None:
    """Nom et prénom séparés quand `familyName` et `givenName` sont tous deux renseignés. Sinon la chaîne brute : `familyName` seul porte souvent le nom complet."""
    given = (as_str(creator.get("givenName")) or "").strip()
    family = (as_str(creator.get("familyName")) or "").strip()
    if given and family:
        return ContributorName.from_parts(family, given)
    return ContributorName.from_raw(as_str(creator.get("name")) or family or given)


def _creator_orcid(creator: Mapping[str, JsonValue]) -> str | None:
    """ORCID depuis `nameIdentifiers` (scheme ORCID ou schemeUri orcid.org)."""
    for identifier in as_sequence(creator.get("nameIdentifiers")):
        fields = as_mapping(identifier)
        if not fields:
            continue
        scheme = (as_str(fields.get("nameIdentifierScheme")) or "").strip().lower()
        if scheme == "orcid" or is_host(as_str(fields.get("schemeUri")), "orcid.org"):
            orcid = normalize_orcid(as_str(fields.get("nameIdentifier")))
            if orcid:
                return orcid
    return None


def _creator_affiliations(
    creator: Mapping[str, JsonValue],
) -> tuple[list[AddressRecord], frozenset[RorId]]:
    """Adresses des affiliations à texte, chacune avec son ROR (`affiliationIdentifier` de schéma `ROR`), et ROR des affiliations sans texte. `affiliation` est une liste de chaînes ou d'objets `{name, affiliationIdentifier, ...}`."""
    addresses: list[AddressRecord] = []
    without_text: set[RorId] = set()
    for aff in as_sequence(creator.get("affiliation")):
        if (text := as_str(aff)) and text.strip():
            addresses.append(AddressRecord(text=text.strip()))
            continue
        obj = as_mapping(aff)
        rors = parse_ror_ids(
            [as_str(obj.get("affiliationIdentifier"))]
            if obj.get("affiliationIdentifierScheme") == "ROR"
            else []
        )
        if (name := as_str(obj.get("name"))) and name.strip():
            addresses.append(AddressRecord(text=name.strip(), ror_ids=rors))
        else:
            without_text |= rors
    return addresses, frozenset(without_text)


def build_datacite_author_records(attributes: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Parse les `creators` DataCite en `AuthorRecord` (sans I/O).

    Un creator `Organizational` donne une contribution source collective. ORCID sur `identifiers`, affiliations brutes → adresses (sans pays), ROR de chaque affiliation sur son adresse, ou sur la contribution source pour une affiliation sans texte, `roles=['author']` explicite.
    """
    creators = attributes.get("creators") or []
    if not isinstance(creators, list):
        return []

    ids_by_position = [
        contributor_identifiers(orcid=_creator_orcid(c)) if isinstance(c, dict) else None
        for c in creators
    ]

    records: list[AuthorRecord] = []
    for position, creator in enumerate(creators):
        if not isinstance(creator, dict):
            continue
        name = _creator_name(creator)
        if name is None:
            continue
        ids = ids_by_position[position]
        addresses, source_contribution_rors = _creator_affiliations(creator)
        records.append(
            AuthorRecord(
                position=position,
                name=name,
                collective=creator.get("nameType") == "Organizational",
                roles=[ContributionRole.AUTHOR],
                identifiers=ids if ids else None,
                addresses=addresses,
                ror_ids=source_contribution_rors,
            )
        )
    return records


def extract_datacite_author_block(attributes: Mapping[str, JsonValue]) -> AuthorBlock:
    """Bloc auteurs des attributs DataCite : `creators`."""
    return {"creators": attributes.get("creators")}


def datacite_doi(attributes: Mapping[str, JsonValue], staging_doi: str | None) -> str | None:
    """DOI du nœud : `attributes.doi`, à défaut celui de sa ligne de `staging`."""
    return clean_doi(as_str(attributes.get("doi"))) or staging_doi


def datacite_source_record(
    attributes: Mapping[str, JsonValue], staging_id: int, doi: str, containers: Containers
) -> SourceRecordUpsert:
    """Enregistrement source DataCite d'un nœud, identifié par son DOI."""
    title = get_title(attributes)
    publication_year = extract_datacite_publication_year(attributes, max_year=today().year + 1)
    # Garanti par `SourceNormalizer`, qui filtre les enregistrements sources sans titre ou sans année.
    assert isinstance(title, str) and isinstance(publication_year, int)
    container_title, _ = get_container(attributes)
    related_dois = extract_related_dois(attributes, doi)
    external_ids: dict[str, JsonValue] = {}
    if related_dois:
        external_ids[ExternalIdType.RELATED_DOIS] = related_dois
    if isbns := get_isbns(attributes):
        external_ids[ExternalIdType.ISBN] = isbns
    return SourceRecordUpsert(
        source="datacite",
        source_id=doi,
        staging_id=staging_id,
        doi=doi,
        external_ids=external_ids or None,
        title=title,
        publication_year=publication_year,
        raw_doc_type=extract_datacite_doc_type_token(attributes),
        serial_id=containers.serial_id,
        monograph_id=containers.monograph_id,
        container_title=container_title if not containers.serial_id else None,
        raw_language=get_language(attributes),
        biblio=get_biblio(attributes),
        abstract=get_abstract(attributes),
        keywords=get_keywords(attributes),
        oa_status=None,
        license=datacite_license(attributes.get("rightsList")),
        impact=Impact(cited_by_count=get_cited_by_count(attributes)).to_json(),
        source_extras=extract_datacite_source_extras(attributes),
    )


class DataciteNormalizer(SourceNormalizer):
    SOURCE = "datacite"
    DEFAULT_BATCH_SIZE = 100

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        attributes = row.raw_data.get("attributes")
        if not isinstance(attributes, dict):
            return None, None
        return get_title(attributes), extract_datacite_publication_year(
            attributes, max_year=today().year + 1
        )

    def parse(self, row: StagingRow) -> Document | None:
        """Les `attributes` du nœud JSON:API, refusés sans DOI."""
        attributes = row.raw_data.get("attributes")
        # Garanti par `SourceNormalizer` : `minimal_metadata` rend (None, None) sinon.
        assert isinstance(attributes, dict)
        return attributes if datacite_doi(attributes, row.doi) else None

    def publisher(self, doc: Document) -> PublisherFacts | None:
        name = get_publisher_name(doc)
        return PublisherFacts(name) if name else None

    def container_facts(self, doc: Document) -> ContainerDescription:
        return get_container_facts(doc)

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        doi = datacite_doi(doc, row.doi)
        assert doi, "garanti par `parse`"
        return datacite_source_record(doc, row.id, doi, containers)

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_datacite_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_datacite_author_records(block)
