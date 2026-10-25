"""Détail d'une publication."""

from sqlalchemy import Connection, text

from application.ports.read_models.publications_queries import (
    AccessLinkOut,
    ConsolidatedContributionOut,
    ExternalIdentifierOut,
    PublicationDetailCore,
    PublicationDetailResponse,
    RelatedPublicationOut,
    SourceRecordOut,
    StructureInfo,
    ThesesContributionOut,
    ThesisMeta,
)
from application.ports.read_models.subjects_queries import SubjectOut
from domain.platforms.registry import HAL
from domain.publications.access import Access, Copy, access
from domain.publications.doc_types import DocType
from domain.publications.relations import RelationType, inverse_relation
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.metadata_correction.shared_doi import CONVERGENCE_CASES
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import Source
from infrastructure.read_models.sql_fragments import (
    contribution_has_source,
    contributor_display_name,
)
from infrastructure.sql_fragments import active_issns, corrected_by


def get_publication_relations(conn: Connection, publication_id: int) -> list[RelatedPublicationOut]:
    """Publications apparentées, des deux sens, vues depuis `publication_id`.

    Les arêtes sortantes (`from_publication_id = publication_id`) gardent leur type ; les entrantes (`target_publication_id = publication_id`) sont inversées pour se lire depuis la publication courante. La cible porte ses métadonnées si elle est au corpus, sinon seul son DOI est connu. Dédupliqué par (type, cible) — une paire déclarée des deux côtés ne s'affiche qu'une fois.
    """
    rows = conn.execute(
        text("""
            WITH rel AS (
                SELECT r.relation_type::text AS rtype, r.target_doi AS other_doi,
                       r.target_publication_id AS other_id, r.source, false AS incoming
                FROM publication_relations r
                WHERE r.from_publication_id = :pid
                UNION ALL
                SELECT r.relation_type::text, src.doi, r.from_publication_id, r.source, true
                FROM publication_relations r
                JOIN publications src ON src.id = r.from_publication_id
                WHERE r.target_publication_id = :pid
            )
            SELECT rel.rtype, rel.other_doi, rel.other_id, rel.source, rel.incoming,
                   p.title AS other_title, p.publication_year AS other_year,
                   p.doc_type::text AS other_doc_type
            FROM rel
            LEFT JOIN publications p ON p.id = rel.other_id
            ORDER BY rel.rtype, p.publication_year DESC NULLS LAST
        """),
        {"pid": publication_id},
    ).all()
    out: list[RelatedPublicationOut] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        relation_type = r.rtype
        if r.incoming:
            relation_type = inverse_relation(RelationType(relation_type)).value
        # Clé de la cible : son `publication_id` si au corpus, sinon son DOI (cible hors corpus, sans ligne `publications`). Le DOI peut être absent d'une cible au corpus, d'où la bascule sur l'id.
        target_key = f"id:{r.other_id}" if r.other_id is not None else f"doi:{r.other_doi}"
        key = (relation_type, target_key)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            RelatedPublicationOut(
                relation_type=relation_type,
                doi=r.other_doi,
                publication_id=r.other_id,
                title=r.other_title,
                publication_year=r.other_year,
                doc_type=r.other_doc_type,
                source=r.source,
            )
        )
    return out


def structures_by_id(conn: Connection, ids: set[int]) -> dict[str, StructureInfo]:
    """Acronyme, nom et type des structures `ids`, par identifiant en texte."""
    if not ids:
        return {}
    rows = conn.execute(
        text("""
            SELECT id, acronym, name, structure_type::text AS type FROM structures
            WHERE id = ANY(:ids)
        """),
        {"ids": list(ids)},
    ).all()
    return {str(s.id): StructureInfo(acronym=s.acronym, name=s.name, type=s.type) for s in rows}


def get_publication_detail(
    conn: Connection, publication_id: int
) -> PublicationDetailResponse | None:
    """Détail complet d'une publication : métadonnées, sources, contributions.

    Retourne None si la publication n'existe pas (caller = 404).
    """
    publication_row = conn.execute(
        text(f"""
            SELECT p.id, p.title, p.publication_year, p.doi, p.doc_type::text AS doc_type,
                   p.oa_status::text AS oa_status,
                   p.license::text AS license, p.deposit_license::text AS deposit_license,
                   p.language, p.container_title, d.abstract, d.keywords,
                   j.id AS serial_id, j.title AS journal_title,
                   CASE WHEN j.id IS NOT NULL THEN {active_issns("j.id")} END AS serial_issns,
                   j.apc_amount, j.apc_currency,
                   j.oa_model,
                   m.id AS monograph_id, m.title AS monograph_title,
                   pub.id AS publisher_id, pub.name AS publisher_name,
                   dp.ra AS doi_ra
            FROM publications p
            LEFT JOIN publications_detail d ON d.publication_id = p.id
            LEFT JOIN serials j ON j.id = p.serial_id
            LEFT JOIN monographs m ON m.id = p.monograph_id
            LEFT JOIN publishers pub ON pub.id = p.publisher_id
            LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(p.doi, '/', 1)
            WHERE p.id = :pid
        """),
        {"pid": publication_id},
    ).one_or_none()
    if not publication_row:
        return None
    # Mots-clés libres (agrégat des sources) : hors référentiel `subjects`, retournés à part.
    keywords = publication_row.keywords or []

    sources_rows = conn.execute(
        text(f"""
            SELECT sr.source, sr.source_id, sr.oa_status, sr.doi, sr.hal_collections, sr.countries,
                   COALESCE({corrected_by("doi", "sr")} = ANY(:convergence_cases), false)
                       AS is_secondary
            FROM source_records sr
            WHERE sr.publication_id = :pid
            ORDER BY sr.created_at DESC
        """),
        {"pid": publication_id, "convergence_cases": list(CONVERGENCE_CASES)},
    ).all()
    sources = [
        SourceRecordOut(
            source=r.source,
            source_id=r.source_id,
            oa_status=r.oa_status,
            doi=r.doi,
            hal_collections=r.hal_collections,
            countries=r.countries,
            is_secondary=r.is_secondary,
        )
        for r in sources_rows
    ]

    auth_rows = conn.execute(
        text(f"""
            SELECT a.reference_position AS author_position, a.in_perimeter, a.is_corresponding,
                   (SELECT array_agg(aus.structure_id ORDER BY aus.structure_id)
                    FROM contribution_structures aus
                    WHERE aus.contribution_id = a.id) AS structure_ids,
                   {contribution_has_source(Source.HAL.value)} AS source_hal,
                   {contribution_has_source(Source.OPENALEX.value)} AS source_openalex,
                   {contribution_has_source(Source.WOS.value)} AS source_wos,
                   {contribution_has_source(Source.SCANR.value)} AS source_scanr,
                   pe.id AS person_id, pe.last_name, pe.first_name,
                   EXISTS (SELECT 1 FROM hr_records pr WHERE pr.person_id = pe.id) AS has_rh
            FROM contributions a
            JOIN persons pe ON pe.id = a.person_id
            WHERE a.publication_id = :pid
            ORDER BY a.reference_position
        """),
        {"pid": publication_id},
    ).all()
    contributions = [
        ConsolidatedContributionOut(
            author_position=r.author_position,
            in_perimeter=r.in_perimeter,
            is_corresponding=r.is_corresponding,
            structure_ids=r.structure_ids,
            source_hal=r.source_hal,
            source_openalex=r.source_openalex,
            source_wos=r.source_wos,
            source_scanr=r.source_scanr,
            person_id=r.person_id,
            last_name=r.last_name,
            first_name=r.first_name,
            has_rh=r.has_rh,
        )
        for r in auth_rows
    ]

    theses_rows = conn.execute(
        text(f"""
            SELECT sc.id, sc.author_position, {contributor_display_name()} AS full_name, g.person_id,
                   sc.roles, sc.in_perimeter
            FROM source_contributions sc
            LEFT JOIN aligned_source_contributions gm ON gm.source_contribution_id = sc.id
            LEFT JOIN contributions g ON g.id = gm.contribution_id
            WHERE sc.source_record_id = (
                SELECT id FROM source_records
                WHERE source = '{Source.THESES.value}' AND publication_id = :pid
                ORDER BY created_at DESC
                LIMIT 1
            )
            ORDER BY sc.author_position NULLS LAST, full_name
        """),
        {"pid": publication_id},
    ).all()
    theses_contributions = [
        ThesesContributionOut(
            id=r.id,
            author_position=r.author_position,
            full_name=r.full_name,
            person_id=r.person_id,
            roles=r.roles,
            in_perimeter=r.in_perimeter,
        )
        for r in theses_rows
    ]

    thesis_meta: ThesisMeta | None = None
    if publication_row.doc_type in (DocType.THESIS, DocType.ONGOING_THESIS):
        extras_row = conn.execute(
            text(f"""
                SELECT sr.source_extras AS source_record_extras, sr.topics->>'discipline' AS discipline,
                       p.source_extras AS publication_extras
                FROM publications p
                LEFT JOIN source_records sr
                       ON sr.publication_id = p.id AND sr.source = '{Source.THESES.value}'
                WHERE p.id = :pid
                LIMIT 1
            """),
            {"pid": publication_id},
        ).one_or_none()
        if extras_row:
            source_record_extras = extras_row.source_record_extras or {}
            publication_extras = extras_row.publication_extras or {}
            thesis_meta = ThesisMeta(
                discipline=extras_row.discipline,
                ecoles_doctorales=source_record_extras.get(SourceExtra.ECOLES_DOCTORALES),
                partenaires=source_record_extras.get(SourceExtra.PARTENAIRES),
                date_soutenance=source_record_extras.get(SourceExtra.DATE_SOUTENANCE)
                or publication_extras.get(SourceExtra.DATE_SOUTENANCE),
                date_inscription=source_record_extras.get(SourceExtra.DATE_INSCRIPTION)
                or publication_extras.get(SourceExtra.DATE_INSCRIPTION),
            )

    subjects = get_publication_subjects(conn, publication_id)
    relations = get_publication_relations(conn, publication_id)
    external_identifiers = get_publication_external_identifiers(conn, publication_id)
    publication_access = access(get_publication_copies(conn, publication_id))

    structures = structures_by_id(
        conn, {sid for a in contributions for sid in a.structure_ids or []}
    )

    return PublicationDetailResponse(
        publication=PublicationDetailCore(
            id=publication_row.id,
            title=publication_row.title,
            publication_year=publication_row.publication_year,
            doi=publication_row.doi,
            doi_ra=publication_row.doi_ra,
            doc_type=publication_row.doc_type,
            oa_status=publication_row.oa_status,
            license=publication_row.license,
            deposit_license=publication_row.deposit_license,
            language=publication_row.language,
            container_title=publication_row.container_title,
            abstract=publication_row.abstract,
            serial_id=publication_row.serial_id,
            journal_title=publication_row.journal_title,
            serial_issns=list(publication_row.serial_issns or []),
            apc_amount=publication_row.apc_amount,
            apc_currency=publication_row.apc_currency,
            oa_model=publication_row.oa_model,
            monograph_id=publication_row.monograph_id,
            monograph_title=publication_row.monograph_title,
            publisher_id=publication_row.publisher_id,
            publisher_name=publication_row.publisher_name,
        ),
        sources=sources,
        contributions=contributions,
        theses_contributions=theses_contributions,
        thesis_meta=thesis_meta,
        structures=structures,
        subjects=subjects,
        keywords=keywords,
        relations=relations,
        access_url=publication_access.url,
        access=[
            AccessLinkOut(label=a.label, url=a.url, known=a.known) for a in publication_access.links
        ],
        referenced_by=_referenced_by(sources, publication_access),
        external_identifiers=external_identifiers,
    )


# Identifiants de bases qui référencent la publication, exposés en sidebar, ordre d'affichage. `hal_id` est exclu (déjà couvert par le lien source HAL) ; `related_dois` aussi (signal de dédup, pas un identifiant à afficher). arXiv et PMCID désignent des copies, qui sont des localisations.
_EXTERNAL_IDENTIFIER_KEYS = (
    ("pmid", ExternalIdType.PMID),
    ("nnt", ExternalIdType.NNT),
)

# Sources dont l'enregistrement est la page du DOI, déjà affiché.
_DOI_SOURCES = frozenset({Source.CROSSREF, Source.DATACITE})

# Sources qui sont aussi une plateforme.
_SOURCE_PLATFORMS: dict[str, str] = {Source.HAL: HAL.name}


def get_publication_copies(conn: Connection, publication_id: int) -> list[Copy]:
    """Localisations des enregistrements sources de la publication, hors formes secondaires. La copie qu'un enregistrement HAL donne de HAL est décrite par sa plateforme."""
    rows = conn.execute(
        text(f"""
            SELECT l.url, l.version, l.is_oa, pl.name AS platform,
                   (sr.source = 'hal' AND pl.openalex_id = ANY(:hal_ids)) AS described_by_platform,
                   sr.id AS arrival
            FROM source_record_locations l
            JOIN source_records sr ON sr.id = l.source_record_id
            LEFT JOIN platforms pl ON pl.id = l.platform_id
            WHERE sr.publication_id = :pid
              AND NOT COALESCE({corrected_by("doi", "sr")} = ANY(:convergence_cases), false)
        """),
        {
            "pid": publication_id,
            "hal_ids": list(HAL.openalex_ids),
            "convergence_cases": list(CONVERGENCE_CASES),
        },
    ).all()
    return [
        Copy(
            url=r.url,
            version=r.version,
            is_oa=r.is_oa,
            platform=r.platform,
            described_by_platform=r.described_by_platform,
            arrival=r.arrival,
        )
        for r in rows
    ]


def _referenced_by(sources: list[SourceRecordOut], access: Access) -> list[SourceRecordOut]:
    """Sources qui référencent la publication sans en donner de copie : une source dont la plateforme figure parmi les liens d'accès en est retirée."""
    platforms = {link.label for link in access.links}
    return [
        s
        for s in sources
        if s.source not in _DOI_SOURCES and _SOURCE_PLATFORMS.get(s.source) not in platforms
    ]


def get_publication_external_identifiers(
    conn: Connection, publication_id: int
) -> list[ExternalIdentifierOut]:
    """Identifiants externes (arXiv, PMID, PMCID, NNT) agrégés depuis les `external_ids` des `source_records` de la publication, dédupliqués, dans l'ordre `_EXTERNAL_IDENTIFIER_KEYS`.

    Un NNT déjà porté par une source `theses` est omis : le `source_id` de cette source *est* le NNT, et son lien theses.fr couvre déjà l'identifiant (même raison que l'exclusion de `hal_id`, couvert par le lien source HAL)."""
    rows = conn.execute(
        text("""
            SELECT sr.source::text, sr.source_id, sr.external_ids FROM source_records sr
            WHERE sr.publication_id = :pid AND sr.external_ids IS NOT NULL
        """),
        {"pid": publication_id},
    ).all()
    nnt_covered_by_theses = {source_id for source, source_id, _ in rows if source == "theses"}
    out: list[ExternalIdentifierOut] = []
    for id_type, key in _EXTERNAL_IDENTIFIER_KEYS:
        seen: set[str] = set()
        for _source, _source_id, external_ids in rows:
            value = external_ids.get(key)
            if not (isinstance(value, str) and value) or value in seen:
                continue
            if id_type == "nnt" and value in nnt_covered_by_theses:
                continue
            seen.add(value)
            out.append(ExternalIdentifierOut(type=id_type, value=value))
    return out


def get_publication_subjects(conn: Connection, publication_id: int) -> list[SubjectOut]:
    """Sujets (concepts) attachés à une publication, dédupliqués par `subject_id`.

    Les sources qui ont annoté chaque sujet sont agrégées dans `sources`. Triés par label, insensible à la casse.
    """
    rows = conn.execute(
        text("""
            SELECT s.id, s.label, s.language,
                   array_agg(DISTINCT ps.source::text ORDER BY ps.source::text) AS sources
            FROM publication_subjects ps
            JOIN subjects s ON s.id = ps.subject_id
            WHERE ps.publication_id = :pid
            GROUP BY s.id
            ORDER BY lower(s.label)
        """),
        {"pid": publication_id},
    ).all()
    return [
        SubjectOut(id=r.id, label=r.label, language=r.language, sources=r.sources) for r in rows
    ]
