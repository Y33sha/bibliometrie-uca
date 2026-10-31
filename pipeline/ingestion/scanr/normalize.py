"""Normalisation des enregistrements sources ScanR."""

from collections.abc import Mapping
from urllib.parse import urlsplit

from domain.countries import normalize_country_code
from domain.normalize import drop_flattened_mathml
from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import map_role, merge_roles
from domain.publications.doc_types import DOC_TYPE_FAMILIES
from domain.publications.identifiers import extract_hal_id_from_url
from domain.publications.licenses import normalize_license
from domain.serials.containers import ContainerDescription
from domain.serials.issns import source_issns
from domain.source_records.biblio import compact_biblio
from domain.source_records.doc_types import map_doc_type
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.impact import Impact
from domain.source_records.source_extras import SourceExtra
from domain.structures.identifiers import RorId, parse_ror_ids
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_strs
from pipeline.ingestion.common.locations import LocationFacts
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
    scanr_derived_identifier,
    select_leaf_affiliations,
    split_scanr_concepts,
)
from pipeline.transformation.publishing.find_or_create import (
    Containers,
)


def get_title(doc: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le titre par défaut du document, nettoyé par `drop_flattened_mathml`."""
    title = doc.get("title")
    text = as_str(title.get("default")) if isinstance(title, Mapping) else as_str(title)
    if not text:
        return None
    return drop_flattened_mathml(text) or None


def get_publisher(doc: Mapping[str, JsonValue]) -> PublisherFacts | None:
    """Renvoie l'éditeur du document : celui de sa source (`source.publisher`)."""
    publisher_name = as_str(as_mapping(doc.get("source")).get("publisher"))
    return PublisherFacts(publisher_name) if publisher_name else None


def is_thesis(doc: Mapping[str, JsonValue]) -> bool:
    """Renvoie vrai si le document est une thèse ou une habilitation : `source.title` nomme alors l'université de soutenance, hors conteneur."""
    return map_doc_type(as_str(doc.get("type")) or "", "scanr") in DOC_TYPE_FAMILIES["theses"].types


def get_container_facts(doc: Mapping[str, JsonValue]) -> ContainerDescription:
    """Décrit le conteneur d'un document d'après ScanR.

    `source.title` est la revue d'un article, le congrès d'une communication (type `proceedings`), et la plateforme de l'éditeur d'un chapitre : un chapitre reçoit sa seule collection, quand un ISSN la désigne. ScanR omet les ISBN.
    """
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


def _address(url: str) -> str:
    """Renvoie une adresse comparable : sans schéma, sans `www.`, sans barre finale, en minuscules."""
    parts = urlsplit(url.strip().lower())
    return f"{parts.netloc.removeprefix('www.')}{parts.path.rstrip('/')}"


def get_locations(doc: Mapping[str, JsonValue]) -> list[LocationFacts]:
    """Renvoie la copie ouverte (`oaEvidence`), puis la page du document (`landingPage`) quand elle désigne une autre adresse.

    La page de la copie ouverte est `oaEvidence.landingPageUrl`, à défaut la page du document quand elle désigne le même dépôt HAL, à défaut `oaEvidence.url`. L'ouverture de la page du document est inconnue. Seule la licence d'une copie chez l'éditeur est normalisée, comme celle de l'enregistrement source.
    """
    landing = as_str(doc.get("landingPage"))
    evidence = as_mapping(doc.get("oaEvidence"))
    evidence_url = as_str(evidence.get("url"))
    locations: list[LocationFacts] = []
    if evidence_url:
        landing_hal_id = extract_hal_id_from_url(landing)
        url = as_str(evidence.get("landingPageUrl")) or evidence_url
        if url == evidence_url and landing and landing_hal_id is not None:
            if landing_hal_id == extract_hal_id_from_url(evidence_url):
                url = landing
        pdf_url = as_str(evidence.get("pdfUrl")) or evidence_url
        if _address(pdf_url) == _address(url):
            pdf_url = None
        host_type = as_str(evidence.get("hostType"))
        locations.append(
            LocationFacts(
                url=url,
                pdf_url=pdf_url,
                version=as_str(evidence.get("version")),
                license=normalize_license(as_str(evidence.get("license")))
                if host_type == "publisher"
                else None,
                is_oa=True,
            )
        )
    if landing and all(_address(landing) != _address(loc.url) for loc in locations):
        locations.append(LocationFacts(url=landing))
    return locations


# Type d'identifiant de chaque type d'`externalIds` lu.
_EXTERNAL_ID_TYPES = {
    "doi": SourceIdentifierType.DOI,
    "hal": SourceIdentifierType.HAL_ID,
    "pmid": SourceIdentifierType.PMID,
}


def scanr_identifiers(doc: Mapping[str, JsonValue], scanr_id: str) -> tuple[SourceIdentifier, ...]:
    """Renvoie les identifiants d'un document ScanR.

    Ceux de ses `externalIds` sont secondaires. L'identifiant contenu dans l'identifiant ScanR est dérivé (`scanr_derived_identifier`).
    """
    identifiers: list[SourceIdentifier] = []
    for entry in as_sequence(doc.get("externalIds")):
        eid = as_mapping(entry)
        id_type = _EXTERNAL_ID_TYPES.get((as_str(eid.get("type")) or "").lower())
        if id_type and (value := as_str(eid.get("id"))):
            identifiers.append(SourceIdentifier(id_type, value, SourceIdentifierRole.SECONDARY))
    if derived := scanr_derived_identifier(scanr_id):
        identifiers.append(derived)
    return tuple(identifiers)


def scanr_source_record(  # noqa: C901
    doc: Mapping[str, JsonValue],
    staging_id: int,
    scanr_id: str,
    containers: Containers,
) -> SourceRecordUpsert:
    """Construit l'enregistrement source ScanR d'un document.

    Le titre du conteneur (`source.title`) est gardé seulement sans revue, hors thèses. L'API ScanR est sans langue.
    """
    abstract = as_str(as_mapping(doc.get("summary")).get("default"))

    kw_val = as_mapping(doc.get("keywords")).get("default")
    if isinstance(kw_val, str) and kw_val:
        keywords = [k.strip() for k in kw_val.split(",") if k.strip()] or None
    elif items := as_sequence(kw_val):
        keywords = [str(k).strip() for k in items if k] or None
    else:
        keywords = None

    # `domains` contient les concepts ScanR : wikidata et mots-clés rejoignent les mots-clés, les vedettes sudoc forment les sujets. `topics`, copie des topics OpenAlex déjà fournis par la source OpenAlex, reste ignoré.
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

    # Éditeur nommé par ScanR.
    source = as_mapping(doc.get("source"))
    biblio_json = compact_biblio(publisher=as_str(source.get("publisher")))

    return SourceRecordUpsert(
        source="scanr",
        source_id=scanr_id,
        staging_id=staging_id,
        identifiers=scanr_identifiers(doc, scanr_id),
        title=get_title(doc) or "",
        publication_year=as_int(doc.get("year")),
        raw_doc_type=as_str(doc.get("type")),
        serial_id=containers.serial_id,
        monograph_id=containers.monograph_id,
        container_title=(
            as_str(source.get("title")) if not (containers.serial_id or is_thesis(doc)) else None
        ),
        raw_language=None,
        biblio=biblio_json,
        abstract=abstract,
        keywords=keywords,
        topics=topics,
        license=normalize_license(publisher_license),
        urls=urls or None,
        impact=Impact(cited_by_count=cited_by_count).to_json(),
        source_extras={SourceExtra.LICENSE: raw_license} if raw_license else None,
    )


def build_scanr_author_records(doc: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Lit les contributions sources d'un document ScanR.

    - Les identifiants `orcid` et `idref` viennent de `denormalized`, les rôles de `map_role`.
    - Une affiliation feuille sans `structId` devient une adresse, avec les pays détectés par ScanR dans son texte (`detected_countries`).
    - Une affiliation feuille avec `structId` est une structure HAL de la contribution source : son nom est celui d'une fiche du référentiel HAL, et reste hors des adresses.
    - Le ROR d'une affiliation va sur son adresse, ou sur la contribution source pour une affiliation sans adresse.
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
    """Fusionne les entrées d'une même personne en une contribution source, comme chez theses.fr.

    ScanR liste une personne une fois par rôle (membre du jury et rapporteur). Une entrée de même nom et de mêmes identifiants qu'une précédente, avec un autre rôle, se fond dans celle-ci : rôles (`merge_roles`), adresses et structures réunis. Une entrée sans rôle nouveau reste à part. Les positions se renumérotent dans l'ordre.
    """
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
    """Renvoie le bloc auteurs d'un document ScanR : `authors`."""
    return {"authors": doc.get("authors")}


class ScanrNormalizer(SourceNormalizer):
    SOURCE = "scanr"
    DEFAULT_BATCH_SIZE = 100

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return get_title(row.raw_data), as_int(row.raw_data.get("year"))

    def publisher(self, doc: Document) -> PublisherFacts | None:
        return get_publisher(doc)

    def container_facts(self, doc: Document) -> ContainerDescription | None:
        return None if is_thesis(doc) else get_container_facts(doc)

    def locations(self, doc: Document) -> list[LocationFacts]:
        return get_locations(doc)

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        return scanr_source_record(doc, row.id, row.source_id, containers)

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_scanr_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_scanr_author_records(block)
