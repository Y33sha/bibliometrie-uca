"""Normalisation des données OpenAlex : staging → tables structurées."""

from collections import defaultdict
from collections.abc import Iterable, Mapping

from domain.countries import normalize_country_code
from domain.persons.contributor_name import ContributorName
from domain.platforms.platform import PlatformType, is_catalog_record
from domain.platforms.registry import known_platform_of_source
from domain.publications.contribution_roles import ContributionRole
from domain.publications.identifiers import clean_doi, extract_doi_from_url, extract_hal_id_from_url
from domain.publications.licenses import normalize_license
from domain.serials.containers import ContainerDescription
from domain.serials.issns import source_issns
from domain.serials.serial import OaModel
from domain.source_records.biblio import compact_biblio
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.impact import Impact
from domain.source_records.source_extras import SourceExtra
from domain.structures.identifiers import RorId, parse_ror_ids
from domain.types import (
    JsonValue,
    as_bool,
    as_float,
    as_int,
    as_mapping,
    as_sequence,
    as_str,
    as_strs,
)
from pipeline.ingestion.common.locations import LocationFacts, PlatformFacts
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
from pipeline.ingestion.openalex.payload import (
    OpenalexLocation,
    extract_external_ids_from_urls,
    extract_nnt_from_location,
    is_theses_fr_location,
    map_openalex_oa_status,
    parse_primary_location,
    short_openalex_id,
    should_skip_publisher_serial,
)
from pipeline.transformation.publishing.find_or_create import (
    Containers,
)

# =============================================================
# UTILITAIRES
# =============================================================


def extract_locations_data(
    work: Mapping[str, JsonValue],
) -> tuple[list[str], dict[str, JsonValue]]:
    """Extrait les URLs et identifiants depuis les locations d'un work OpenAlex.

    Retourne (urls, external_ids) où :
      - urls : liste dédupliquée de landing_page_url et pdf_url
      - external_ids : dict d'identifiants (nnt, pmid, pmcid, arxiv_id scalaires ; hal_id et related_dois **listes**)

    hal_id et related_dois sont collectés depuis les URLs **et** depuis `location.id` (formes OAI-PMH `pmh:oai:HAL:<halid>` et `doi:<doi>`), source structurée présente même quand la landing page est une page éditeur. related_dois contient ici **tous** les DOI des locations ; l'appelant en retire le DOI primaire (top-level) de la publication.
    """
    urls: list[str] = []
    seen: set[str] = set()
    location_ids: list[str] = []
    for entry in as_sequence(work.get("locations")):
        loc = as_mapping(entry)
        for key in ("landing_page_url", "pdf_url"):
            url = as_str(loc.get(key))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        if loc_id := as_str(loc.get("id")):
            location_ids.append(loc_id)

    external_ids: dict[str, JsonValue] = dict(extract_external_ids_from_urls(urls))
    # hal_id et related_dois sont multivalués et apparaissent aussi dans les location.id (absents des URLs quand la landing page est une page éditeur).
    # On balaie URLs + location.id en une passe.
    hal_ids: list[str] = [
        h for e in as_sequence(external_ids.get(ExternalIdType.HAL_ID)) if (h := as_str(e))
    ]
    related_dois: list[str] = []
    for s in (*urls, *location_ids):
        if (hal_id := extract_hal_id_from_url(s)) and hal_id not in hal_ids:
            hal_ids.append(hal_id)
        if (doi := extract_doi_from_url(s)) and doi not in related_dois:
            related_dois.append(doi)
    if hal_ids:
        external_ids[ExternalIdType.HAL_ID] = hal_ids
    if related_dois:
        external_ids[ExternalIdType.RELATED_DOIS] = related_dois
    return urls, external_ids


def get_locations(work: Mapping[str, JsonValue]) -> list[LocationFacts]:
    """Localisations du work, hors fiches de catalogue. Une source de type `repository` donne la plateforme de la localisation."""
    locations: list[LocationFacts] = []
    for entry in as_sequence(work.get("locations")):
        loc = as_mapping(entry)
        pdf_url = as_str(loc.get("pdf_url"))
        url = as_str(loc.get("landing_page_url")) or pdf_url
        if not url or is_catalog_record(url):
            continue
        location_id = as_str(loc.get("id")) or ""
        locations.append(
            LocationFacts(
                url=url,
                pdf_url=pdf_url,
                oai_id=location_id.removeprefix("pmh:") if location_id.startswith("pmh:") else None,
                version=as_str(loc.get("version")),
                license=normalize_license(as_str(loc.get("license"))),
                is_oa=as_bool(loc.get("is_oa")),
                platform=_repository(as_mapping(loc.get("source"))),
            )
        )
    return locations


def _repository(source: Mapping[str, JsonValue]) -> PlatformFacts | None:
    """Plateforme d'une source OpenAlex de type `repository`, nommée comme OpenAlex la nomme. Son type est celui de la liste des plateformes connues, à défaut entrepôt."""
    if as_str(source.get("type")) != "repository":
        return None
    openalex_id = short_openalex_id(as_str(source.get("id")) or "")
    name = as_str(source.get("display_name"))
    if not openalex_id or not name:
        return None
    known = known_platform_of_source(openalex_id)
    return PlatformFacts(
        openalex_id, name, known.platform_type if known else PlatformType.REPOSITORY
    )


def reconstruct_abstract(inverted_index: Mapping[str, JsonValue] | None) -> str | None:
    """Reconstruit le texte de l'abstract depuis l'inverted index OpenAlex.

    Le format est {mot: [positions]} → on reconstitue le texte en ordre.
    """
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, word_positions in inverted_index.items():
        for raw in as_sequence(word_positions):
            if (idx := as_int(raw)) is not None:
                positions[idx] = word
    if not positions:
        return None
    return " ".join(positions[k] for k in sorted(positions))


def extract_topics(work: Mapping[str, JsonValue]) -> list[dict[str, JsonValue]] | None:
    """Extrait les topics OpenAlex sous forme de liste simplifiée."""
    topics: list[dict[str, JsonValue]] = []
    for entry in as_sequence(work.get("topics")):
        t = as_mapping(entry)
        topic: dict[str, JsonValue] = {}
        for level in ("domain", "field", "subfield", "topic"):
            obj = as_mapping(t.get(level)) or (t if level == "topic" else {})
            if name := as_str(obj.get("display_name")):
                topic[level] = name
        if (score := t.get("score")) is not None:
            topic["score"] = score
        if topic:
            topics.append(topic)
    return topics or None


def extract_impact(work: Mapping[str, JsonValue]) -> Impact:
    """Indicateurs de citation OpenAlex : nombre de citations, FWCI et percentile de citations normalisé."""
    percentile = as_mapping(work.get("citation_normalized_percentile"))
    return Impact(
        cited_by_count=as_int(work.get("cited_by_count")),
        fwci=as_float(work.get("fwci")),
        citation_percentile=as_float(percentile.get("value")),
        top_10_percent=as_bool(percentile.get("is_in_top_10_percent")),
        top_1_percent=as_bool(percentile.get("is_in_top_1_percent")),
    )


# =============================================================
# PUBLISHERS & JOURNALS
# =============================================================


def get_publisher(work: Mapping[str, JsonValue]) -> PublisherFacts | None:
    """Éditeur du work : l'organisation hôte de la source de sa localisation principale."""
    source = as_mapping(as_mapping(work.get("primary_location")).get("source"))
    publisher_name = as_str(source.get("host_organization_name"))
    if not publisher_name:
        return None
    openalex_id = short_openalex_id(as_str(source.get("host_organization")) or "")
    return PublisherFacts(publisher_name, openalex_id or None)


def get_container_facts(work: Mapping[str, JsonValue]) -> ContainerDescription:
    """Ce qu'OpenAlex dit du conteneur d'un document : la source de sa localisation principale.

    Une source `book series` ou `journal` est la collection d'un livre, d'un chapitre ou d'un article de congrès ; une source `conference` est son volume d'actes. OpenAlex ne donne ni le titre du livre qui contient un chapitre, ni ISBN.
    """
    source = as_mapping(as_mapping(work.get("primary_location")).get("source"))
    title = as_str(source.get("display_name"))

    openalex_id = short_openalex_id(as_str(source.get("id")) or "")
    # OpenAlex ne donne pas le support de ses ISSN.
    issns = source_issns(unknown=as_strs(source.get("issn")), linking=as_str(source.get("issn_l")))

    source_type = as_str(source.get("type"))
    oa_model: OaModel | None = None
    if source_type == "journal":
        oa_model = OaModel.FULL_OA if source.get("is_oa") else OaModel.SUBSCRIPTION
    elif source_type == "repository":
        oa_model = OaModel.REPOSITORY

    return ContainerDescription(
        source="openalex",
        raw_doc_type=as_str(work.get("type")),
        document_title=as_str(work.get("title")) or as_str(work.get("display_name")),
        journal_title=title,
        collection_title=title if source_type in ("book series", "journal") else None,
        book_title=title if source_type == "conference" else None,
        issns=issns,
        openalex_id=openalex_id or None,
        oa_model=oa_model,
        year=as_int(work.get("publication_year")),
    )


# =============================================================
# SOURCE DOCUMENTS (OPENALEX)
# =============================================================


def get_title(work: Mapping[str, JsonValue]) -> str | None:
    """Titre du work, ou à défaut son `display_name`."""
    return as_str(work.get("title")) or as_str(work.get("display_name"))


def get_publication_year(work: Mapping[str, JsonValue]) -> int | None:
    return as_int(work.get("publication_year"))


def get_nnt(primary: OpenalexLocation | None) -> str | None:
    """NNT d'une localisation principale theses.fr."""
    if primary is None or not is_theses_fr_location(primary):
        return None
    return extract_nnt_from_location(primary)


def openalex_source_record(  # noqa: C901
    work: Mapping[str, JsonValue],
    staging_id: int,
    containers: Containers,
    primary: OpenalexLocation | None = None,
) -> SourceRecordUpsert:
    """Enregistrement source OpenAlex d'un work.

    `primary` est la localisation principale déjà analysée ; la fonction l'analyse en son absence. Sans revue identifiée, le titre du conteneur est le nom de la source de la localisation principale.
    """
    openalex_id = short_openalex_id(as_str(work.get("id")) or "")
    if primary is None:
        primary = parse_primary_location(work)

    doi = clean_doi(as_str(work.get("doi")))

    # URLs et identifiants extraits des locations
    urls, external_ids = extract_locations_data(work)
    if nnt := get_nnt(primary):
        external_ids[ExternalIdType.NNT] = nnt
    # related_dois (collecté depuis les locations) = DOI secondaires : on retire
    # le DOI primaire de la publication, qui vit sur la colonne `doi`.
    if related_dois := as_sequence(external_ids.get(ExternalIdType.RELATED_DOIS)):
        if remaining := [d for d in related_dois if d != doi]:
            external_ids[ExternalIdType.RELATED_DOIS] = remaining
        else:
            del external_ids[ExternalIdType.RELATED_DOIS]

    is_retracted = bool(work.get("is_retracted"))

    # Numérotation, éditeur et revue tels qu'OpenAlex les nomme, en parallèle des publishers/serials créés via find_or_create_*.
    # L'éditeur et la revue sont ignorés pour les primary locations qui ne représentent pas un éditeur (HAL, theses.fr, Zenodo, etc.), même critère que la création.
    raw_biblio = as_mapping(work.get("biblio"))
    source = (
        {}
        if should_skip_publisher_serial(primary)
        else as_mapping(as_mapping(work.get("primary_location")).get("source"))
    )
    issn_l = as_str(source.get("issn_l"))
    issns = [i for e in as_sequence(source.get("issn")) if (i := as_str(e)) and i != issn_l]
    biblio_json = compact_biblio(
        volume=as_str(raw_biblio.get("volume")),
        issue=as_str(raw_biblio.get("issue")),
        first_page=as_str(raw_biblio.get("first_page")),
        last_page=as_str(raw_biblio.get("last_page")),
        publisher=as_str(source.get("host_organization_name")),
        journal_title=as_str(source.get("display_name")),
        journal_issn=issns[0] if issns else None,
        journal_eissn=issns[1] if len(issns) > 1 else None,
        journal_issnl=issn_l,
        journal_openalex_id=short_openalex_id(as_str(source.get("id")) or ""),
    )

    # Abstract, keywords, topics
    abstract = reconstruct_abstract(as_mapping(work.get("abstract_inverted_index")))
    words = [
        as_str(as_mapping(k).get("keyword")) or as_str(k) for k in as_sequence(work.get("keywords"))
    ]
    keywords = [m for m in words if m] or None
    topics = extract_topics(work)
    topics_json = topics if topics else None

    # Licence de la localisation principale seule : HAL et Crossref donnent celles de leurs propres localisations. Une localisation sans éditeur (archive, plateforme) garde sa forme brute dans `source_extras`, sans licence normalisée.
    raw_license = as_str(as_mapping(work.get("primary_location")).get("license"))
    publisher_license = None if should_skip_publisher_serial(primary) else raw_license

    return SourceRecordUpsert(
        source="openalex",
        source_id=openalex_id,
        staging_id=staging_id,
        doi=doi,
        external_ids=external_ids or None,
        title=get_title(work) or "",
        publication_year=get_publication_year(work),
        raw_doc_type=as_str(work.get("type")),
        serial_id=containers.serial_id,
        monograph_id=containers.monograph_id,
        container_title=(
            primary.source_display_name if primary and not containers.serial_id else None
        ),
        raw_language=as_str(work.get("language")),
        biblio=biblio_json,
        abstract=abstract,
        keywords=keywords,
        topics=topics_json,
        oa_status=map_openalex_oa_status(
            as_str(as_mapping(work.get("open_access")).get("oa_status"))
        ),
        license=normalize_license(publisher_license),
        urls=urls or None,
        impact=extract_impact(work).to_json(),
        is_retracted=is_retracted,
        source_extras={SourceExtra.LICENSE: raw_license} if raw_license else None,
    )


# =============================================================
# OPENALEX AUTHORS — identifiants sur source_contributions
# =============================================================
# Les entités auteurs OpenAlex sont algorithmiques et non fiables, on garde uniquement l'ORCID quand présent, dans les informations du contributeur (contributor_information.identifiers).


def _extract_openalex_orcid(authorship: Mapping[str, JsonValue]) -> str | None:
    """Extrait l'ORCID déposé par l'auteur sur l'authorship (`raw_orcid`).

    OpenAlex porte deux ORCID par authorship, de provenances opposées :

    - `raw_orcid` (niveau authorship) : recopié tel quel de la métadonnée brute du work telle qu'ingérée par OpenAlex depuis sa source amont (Crossref pour l'essentiel des articles à éditeur). C'est l'ORCID déposé par l'auteur à la soumission — fiable au même titre qu'un ORCID Crossref.
    - `author.orcid` (niveau entité auteur OpenAlex) : ORCID de l'entité désambiguïsée par le clustering nom × affiliation d'OpenAlex, régulièrement fautif.

    On retient `raw_orcid` et on ignore `author.orcid`.
    """
    return as_str(authorship.get("raw_orcid"))


# =============================================================
# OPENALEX AUTHORSHIPS
# =============================================================


def _countries(institutions: Iterable[Mapping[str, JsonValue]]) -> list[str] | None:
    """Codes pays des institutions, triés, ou `None` sans pays."""
    return (
        sorted(
            {
                country
                for i in institutions
                if (country := normalize_country_code(as_str(i.get("country_code"))))
            }
        )
        or None
    )


def _rors(institutions: Iterable[Mapping[str, JsonValue]]) -> frozenset[RorId]:
    return parse_ror_ids(as_str(i.get("ror")) for i in institutions)


def build_openalex_author_records(work: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Parse les authorships d'un work OpenAlex en `AuthorRecord` (sans I/O).

    - nom brut : `raw_author_name`, le nom tel qu'imprimé, `author.display_name` étant celui de l'auteur désambiguïsé ;
    - ORCID déposé (`raw_orcid`) sur `identifiers` ;
    - adresses : les `raw_affiliation_strings` ;
    - pays d'une adresse : `country_code` des institutions que `affiliations` relie à son texte ;
    - ROR des institutions : sur l'adresse dont le texte les désigne, sur la contribution source pour les autres ;
    - `roles=['author']` explicite (OpenAlex ne distingue pas les rôles).
    """
    authorships = [as_mapping(a) for a in as_sequence(work.get("authorships"))]
    ids_by_position = [
        contributor_identifiers(orcid=_extract_openalex_orcid(a)) for a in authorships
    ]

    records: list[AuthorRecord] = []
    for position, authorship in enumerate(authorships):
        name = ContributorName.from_raw(as_str(authorship.get("raw_author_name")))
        if name is None:
            # Sans nom, l'authorship est inexploitable pour le matching personnes.
            continue

        institutions = {
            institution_id: i
            for i in (as_mapping(e) for e in as_sequence(authorship.get("institutions")))
            if (institution_id := as_str(i.get("id")))
        }
        institutions_by_text: dict[str, set[str]] = defaultdict(set)
        for affiliation in as_sequence(authorship.get("affiliations")):
            affiliation = as_mapping(affiliation)
            if text := as_str(affiliation.get("raw_affiliation_string")):
                institutions_by_text[text].update(
                    institution_id
                    for e in as_sequence(affiliation.get("institution_ids"))
                    if (institution_id := as_str(e)) in institutions
                )
        raw_strings = [
            text
            for e in as_sequence(authorship.get("raw_affiliation_strings"))
            if (text := as_str(e))
        ]
        with_text = {i for text in raw_strings for i in institutions_by_text.get(text, ())}

        ids = ids_by_position[position]
        records.append(
            AuthorRecord(
                position=position,
                name=name,
                is_corresponding=bool(authorship.get("is_corresponding")),
                roles=[ContributionRole.AUTHOR],
                identifiers=ids if ids else None,
                addresses=[
                    AddressRecord(
                        text=text,
                        countries=_countries(
                            institutions[i] for i in institutions_by_text.get(text, ())
                        ),
                        ror_ids=_rors(institutions[i] for i in institutions_by_text.get(text, ())),
                    )
                    for text in raw_strings
                ],
                ror_ids=_rors(institutions[i] for i in institutions.keys() - with_text),
            )
        )
    return records


def extract_openalex_author_block(work: Mapping[str, JsonValue]) -> AuthorBlock:
    """Bloc auteurs d'un work OpenAlex : `authorships`."""
    return {"authorships": work.get("authorships")}


class OpenalexNormalizer(SourceNormalizer):
    SOURCE = "openalex"
    DEFAULT_BATCH_SIZE = 500

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return get_title(row.raw_data), get_publication_year(row.raw_data)

    def publisher(self, doc: Document) -> PublisherFacts | None:
        if should_skip_publisher_serial(parse_primary_location(doc)):
            return None
        return get_publisher(doc)

    def container_facts(self, doc: Document) -> ContainerDescription | None:
        if should_skip_publisher_serial(parse_primary_location(doc)):
            return None
        return get_container_facts(doc)

    def locations(self, doc: Document) -> list[LocationFacts]:
        return get_locations(doc)

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        return openalex_source_record(doc, row.id, containers, parse_primary_location(doc))

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_openalex_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_openalex_author_records(block)
