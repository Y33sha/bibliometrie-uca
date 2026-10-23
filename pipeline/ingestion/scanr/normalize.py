"""Normalisation des données ScanR : staging → tables structurées."""

from collections.abc import Mapping

from domain.countries import normalize_country_code
from domain.journals.containers import ContainerDescription
from domain.journals.issns import source_issns
from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import map_role, merge_roles
from domain.publications.identifiers import clean_doi
from domain.publications.licenses import normalize_license
from domain.source_records.biblio import compact_biblio
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.impact import Impact
from domain.source_records.source_extras import SourceExtra
from domain.structures.identifiers import RorId, parse_ror_ids
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_strs
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
from pipeline.ingestion.scanr.payload import (
    derive_scanr_oa_status,
    extract_nnt_from_scanr_id,
    select_leaf_affiliations,
    split_scanr_concepts,
)
from pipeline.transformation.publishing.find_or_create import (
    Containers,
)

# =============================================================
# UTILITAIRES
# =============================================================


def extract_doi(doc: Mapping[str, JsonValue]) -> str | None:
    for entry in as_sequence(doc.get("externalIds")):
        ext = as_mapping(entry)
        if as_str(ext.get("type")) == "doi":
            return clean_doi(as_str(ext.get("id")))
    return None


def get_title(doc: Mapping[str, JsonValue]) -> str | None:
    title = doc.get("title")
    if isinstance(title, Mapping):
        return as_str(title.get("default"))
    return as_str(title)


def get_publisher(doc: Mapping[str, JsonValue]) -> PublisherFacts | None:
    """Éditeur du document : celui de sa source (`source.publisher`)."""
    publisher_name = as_str(as_mapping(doc.get("source")).get("publisher"))
    return PublisherFacts(publisher_name) if publisher_name else None


def _extract_journal_issns(source: Mapping[str, JsonValue]) -> tuple[str | None, str | None]:
    """Extrait (issn, eissn) depuis `source.journalIssns` (array ScanR).

    Heuristique : 1er = print/issn, 2e = electronic/eissn. Les éventuelles entrées supplémentaires (alias, ISSN-L, variantes historiques) sont ignorées. Cohérent avec ce qu'on fait pour OpenAlex.
    """
    issns = as_sequence(source.get("journalIssns"))
    issn = as_str(issns[0]) if len(issns) >= 1 else None
    eissn = as_str(issns[1]) if len(issns) >= 2 else None
    return issn, eissn


def get_container_facts(doc: Mapping[str, JsonValue]) -> ContainerDescription:
    """Ce que ScanR dit du conteneur d'un document. `source.title` est la revue d'un article, le congrès d'une communication (type `proceedings`), et la plateforme de l'éditeur d'un chapitre : un chapitre reçoit sa seule collection, quand un ISSN la désigne. ScanR ne donne pas d'ISBN."""
    source = as_mapping(doc.get("source"))
    title = as_str(source.get("title"))
    raw_type = as_str(doc.get("type"))
    return ContainerDescription(
        source="scanr",
        raw_doc_type=raw_type,
        document_title=get_title(doc),
        journal_title=title,
        collection_title=title,
        book_title=title if raw_type == "proceedings" else None,
        # ScanR ne donne pas le support de ses ISSN.
        issns=source_issns(unknown=as_strs(source.get("journalIssns"))),
        year=as_int(doc.get("year")),
    )


def get_oa_status(doc: Mapping[str, JsonValue]) -> str | None:
    is_open = doc.get("isOa")
    return derive_scanr_oa_status(
        is_open if isinstance(is_open, bool) else None, as_mapping(doc.get("oaEvidence"))
    )


# =============================================================
# SOURCE DOCUMENTS (SCANR)
# =============================================================


def scanr_source_record(  # noqa: C901
    doc: Mapping[str, JsonValue],
    staging_id: int,
    scanr_id: str,
    containers: Containers,
) -> SourceRecordUpsert:
    """Enregistrement source ScanR d'un document.

    Le NNT vient de l'identifiant ScanR (`scanr_id`). Le titre du contenant (`source.title`) est gardé seulement en l'absence de revue. L'API ScanR n'expose pas la langue.
    """
    doi = extract_doi(doc)
    ext: dict[str, JsonValue] = {}
    if nnt := extract_nnt_from_scanr_id(scanr_id):
        ext[ExternalIdType.NNT] = nnt
    # hal_id et related_dois multivalués : un document ScanR peut référencer plusieurs dépôts HAL et plusieurs DOI (preprint/dépôt/édition).
    hal_ids: list[str] = []
    dois: list[str] = []
    for entry in as_sequence(doc.get("externalIds")):
        eid = as_mapping(entry)
        etype = as_str(eid.get("type"))
        value = as_str(eid.get("id"))
        if not etype or not value:
            continue
        etype = etype.lower()
        if etype == "hal" and value not in hal_ids:
            hal_ids.append(value)
        elif etype == "pmid":
            ext[ExternalIdType.PMID] = value
        elif etype == "doi" and (entry_doi := clean_doi(value)) and entry_doi not in dois:
            dois.append(entry_doi)
    if hal_ids:
        ext[ExternalIdType.HAL_ID] = hal_ids
    # related_dois = DOI secondaires (autres que le primaire, qui vit sur `doi`).
    # Le doiUrl ScanR est toujours redondant avec un externalIds type=doi.
    if related_dois := [d for d in dois if d != doi]:
        ext[ExternalIdType.RELATED_DOIS] = related_dois
    external_ids = ext if ext else None

    abstract = as_str(as_mapping(doc.get("summary")).get("default"))

    kw_val = as_mapping(doc.get("keywords")).get("default")
    if isinstance(kw_val, str) and kw_val:
        keywords = [k.strip() for k in kw_val.split(",") if k.strip()] or None
    elif items := as_sequence(kw_val):
        keywords = [str(k).strip() for k in items if k] or None
    else:
        keywords = None

    # `domains` porte les concepts ScanR : wikidata et mots-clés rejoignent les mots-clés, les vedettes sudoc forment les sujets. `topics` reprend les topics OpenAlex, que la source OpenAlex fournit : il n'est pas lu.
    concept_keywords, subjects = split_scanr_concepts(doc.get("domains"))
    known = {k.lower() for k in keywords or ()}
    keywords = [*(keywords or ()), *(k for k in concept_keywords if k.lower() not in known)] or None
    topics = subjects or None

    cbc = as_mapping(doc.get("cited_by_counts_by_year"))
    years = [n for v in cbc.values() if (n := as_int(v)) is not None]
    cited_by_count = sum(years) if years else None

    urls: list[str] = []
    seen: set[str] = set()
    oa_ev = as_mapping(doc.get("oaEvidence"))
    raw_license = as_str(oa_ev.get("license"))
    # La licence d'une localisation d'archive (dépôt HAL…) garde sa forme brute dans `source_extras`, sans licence normalisée : HAL donne la licence de ses dépôts.
    publisher_license = raw_license if oa_ev.get("hostType") == "publisher" else None
    addresses = [doc.get(f) for f in ("landingPage", "doiUrl", "pdfUrl")]
    addresses += [oa_ev.get(f) for f in ("landingPageUrl", "url", "pdfUrl")]
    for raw in addresses:
        u = as_str(raw)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    # Publisher + journal bruts (traçabilité du nom tel que vu par ScanR, en parallèle des publishers/journals créés via find_or_create_*).
    source = as_mapping(doc.get("source"))
    jissn, jeissn = _extract_journal_issns(source)
    biblio_json = compact_biblio(
        publisher=as_str(source.get("publisher")),
        journal_title=as_str(source.get("title")),
        journal_issn=jissn,
        journal_eissn=jeissn,
    )

    return SourceRecordUpsert(
        source="scanr",
        source_id=scanr_id,
        staging_id=staging_id,
        doi=doi,
        external_ids=external_ids,
        title=get_title(doc) or "",
        publication_year=as_int(doc.get("year")),
        raw_doc_type=as_str(doc.get("type")),
        journal_id=containers.journal_id,
        monograph_id=containers.monograph_id,
        container_title=as_str(source.get("title")) if not containers.journal_id else None,
        raw_language=None,
        biblio=biblio_json,
        abstract=abstract,
        keywords=keywords,
        topics=topics,
        oa_status=get_oa_status(doc),
        license=normalize_license(publisher_license),
        urls=urls or None,
        impact=Impact(cited_by_count=cited_by_count).to_json(),
        source_extras={SourceExtra.LICENSE: raw_license} if raw_license else None,
    )


# =============================================================
# SCANR CONTRIBUTIONS
# =============================================================


def build_scanr_author_records(doc: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Parse les auteurs d'un document ScanR en `AuthorRecord` (sans I/O).

    - identifiants `orcid`/`idref` (sous `denormalized`) ;
    - `roles` via `map_role('scanr', role)` ;
    - affiliations feuilles sans `structId` → adresses, chacune avec ses `detected_countries` en `countries` (pays d'autorité détectés dans le texte de l'affiliation) ;
    - affiliations feuilles avec `structId` → structures HAL de la contribution source. Leur nom est celui d'une fiche du référentiel HAL : il n'est pas une adresse ;
    - ROR de chaque affiliation : sur son adresse, sur la contribution source pour les affiliations sans adresse.
    """
    authors = [as_mapping(a) for a in as_sequence(doc.get("authors"))]
    ids_by_position = [
        contributor_identifiers(
            orcid=as_str(as_mapping(a.get("denormalized")).get("orcid")),
            idref=as_str(as_mapping(a.get("denormalized")).get("idref")),
        )
        for a in authors
    ]

    records: list[AuthorRecord] = []
    for position, author_data in enumerate(authors):
        contributor_name = ContributorName.from_raw(as_str(author_data.get("fullName")))
        if contributor_name is None:
            continue

        ids = ids_by_position[position]
        roles, _ = map_role("scanr", as_str(author_data.get("role")))

        addresses: list[AddressRecord] = []
        source_contribution_rors: set[RorId] = set()
        affiliations = [as_mapping(a) for a in as_sequence(author_data.get("affiliations"))]
        leaves = select_leaf_affiliations(affiliations)
        hal_structure_ids = frozenset(
            int(struct_id)
            for leaf in leaves
            if (struct_id := as_str(leaf.get("structId")) or "").isdigit()
        )
        for aff in affiliations:
            rors = parse_ror_ids([as_str(aff.get("ror"))])
            name = (as_str(aff.get("name")) or "").strip()
            is_address = name and not aff.get("structId") and any(aff is leaf for leaf in leaves)
            if not is_address:
                source_contribution_rors |= rors
                continue
            countries = {
                country
                for p in as_sequence(aff.get("detected_countries"))
                if (country := normalize_country_code(as_str(p)))
            }
            addresses.append(
                AddressRecord(text=name, countries=sorted(countries) or None, ror_ids=rors)
            )

        records.append(
            AuthorRecord(
                position=position,
                name=contributor_name,
                roles=roles or None,
                identifiers=ids if ids else None,
                addresses=addresses,
                ror_ids=frozenset(source_contribution_rors),
                hal_structure_ids=hal_structure_ids,
            )
        )
    return merge_person_roles(records)


def merge_person_roles(records: list[AuthorRecord]) -> list[AuthorRecord]:
    """Une contribution source par personne, comme chez theses.fr. scanR liste une personne une fois par rôle (membre du jury et rapporteur). Une entrée de même nom et de mêmes identifiants qu'une précédente, avec un autre rôle, se fond dans celle-ci : rôles (`merge_roles`), adresses et structures réunis. Une entrée qui répète les mêmes rôles reste à part. Les positions se renumérotent dans l'ordre."""
    kept: list[AuthorRecord] = []
    by_person: dict[tuple[object, ...], AuthorRecord] = {}
    for record in records:
        key = (
            record.name.normalized(),
            tuple(sorted((k, str(v)) for k, v in (record.identifiers or {}).items())),
        )
        first = by_person.get(key)
        if first is None or set(record.roles or ()) <= set(first.roles or ()):
            by_person.setdefault(key, record)
            kept.append(record)
            continue
        first.roles = merge_roles([first.roles or [], record.roles or []])
        texts = {a.text for a in first.addresses}
        first.addresses += [a for a in record.addresses if a.text not in texts]
        first.ror_ids |= record.ror_ids
        first.hal_structure_ids |= record.hal_structure_ids
    for position, record in enumerate(kept):
        record.position = position
    return kept


def extract_scanr_author_block(doc: Mapping[str, JsonValue]) -> AuthorBlock:
    """Bloc auteurs d'un document ScanR : `authors`."""
    return {"authors": doc.get("authors")}


class ScanrNormalizer(SourceNormalizer):
    SOURCE = "scanr"
    DEFAULT_BATCH_SIZE = 100

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return get_title(row.raw_data), as_int(row.raw_data.get("year"))

    def publisher(self, doc: Document) -> PublisherFacts | None:
        return get_publisher(doc)

    def container_facts(self, doc: Document) -> ContainerDescription:
        return get_container_facts(doc)

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        return scanr_source_record(doc, row.id, row.source_id, containers)

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_scanr_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_scanr_author_records(block)
