"""Détail d'une publication."""

from collections.abc import Mapping

from sqlalchemy import Connection, text

from domain.documents.doc_types import DocType
from domain.platforms.registry import HAL, espacenet_url
from domain.publications.access import Access, access, access_url
from domain.publications.relations import RelationType, inverse_relation
from domain.source_records.identifiers import SourceIdentifierType
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import Source
from domain.subjects.subject import SubjectVocabulary
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.db.source_record_identifiers import source_record_doi_sql
from infrastructure.read_models.publications.copies import publication_copies
from infrastructure.read_models.publications.models import (
    AccessLinkOut,
    ConsolidatedContributionOut,
    CpcCode,
    ExternalIdentifierOut,
    PatentApplicant,
    PatentApplication,
    PatentMeta,
    PublicationDetailCore,
    PublicationDetailResponse,
    RelatedPublicationOut,
    SourceRecordOut,
    StructureInfo,
    ThesesContributionOut,
    ThesisMeta,
)
from infrastructure.read_models.sql_fragments import (
    contribution_has_source,
    contributor_display_name,
)
from infrastructure.read_models.subjects.models import SubjectOut
from infrastructure.sql_fragments import active_issns, is_laboratory


def get_publication_relations(conn: Connection, publication_id: int) -> list[RelatedPublicationOut]:
    """Renvoie les publications apparentées, dans les deux sens, vues depuis la publication.

    Les relations sortantes gardent leur type ; les entrantes sont inversées pour se lire depuis la publication. Une cible du corpus vient avec ses métadonnées, une cible hors corpus avec son seul DOI. Une paire déclarée des deux côtés s'affiche une fois.
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
            ORDER BY rel.rtype, p.publication_date DESC NULLS LAST
        """),
        {"pid": publication_id},
    ).all()
    out: list[RelatedPublicationOut] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        relation_type = r.rtype
        if r.incoming:
            relation_type = inverse_relation(RelationType(relation_type)).value
        # Clé de la cible : son `publication_id` si elle est dans le corpus, sinon son DOI. Une cible du corpus peut être sans DOI, d'où la clé par identifiant.
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
    """Renvoie l'acronyme, le nom et le type des structures données, par identifiant en texte, et si chacune est un laboratoire."""
    if not ids:
        return {}
    rows = conn.execute(
        text(f"""
            SELECT s.id, s.acronym, s.name, s.structure_type::text AS type,
                   {is_laboratory("s")} AS is_laboratory
            FROM structures s
            WHERE s.id = ANY(:ids)
        """),
        {"ids": list(ids)},
    ).all()
    return {
        str(s.id): StructureInfo(
            acronym=s.acronym, name=s.name, type=s.type, is_laboratory=s.is_laboratory
        )
        for s in rows
    }


_EXTERNAL_IDENTIFIER_TYPES = (SourceIdentifierType.PMID, SourceIdentifierType.NNT)
"""Identifiants de bases référençant la publication, affichés dans la colonne latérale, dans l'ordre d'affichage. Le lien source HAL couvre le `hal_id`, le DOI de la publication ses DOI."""

_DOI_SOURCES = frozenset({Source.CROSSREF, Source.DATACITE})
"""Sources dont l'enregistrement est la page du DOI, déjà affiché."""

_SOURCE_PLATFORMS: dict[str, str] = {Source.HAL: HAL.name}
"""Sources qui sont aussi une plateforme."""


def _referenced_by(sources: list[SourceRecordOut], access: Access) -> list[SourceRecordOut]:
    """Renvoie les sources référençant la publication sans en donner de copie, un enregistrement source par source, le premier de `sources`. Une source dont la plateforme figure parmi les liens d'accès est retirée."""
    platforms = {link.label for link in access.links}
    first_by_source: dict[str, SourceRecordOut] = {}
    for s in sources:
        if s.source not in _DOI_SOURCES and _SOURCE_PLATFORMS.get(s.source) not in platforms:
            first_by_source.setdefault(s.source, s)
    return list(first_by_source.values())


def _applicant_structures(
    conn: Connection, rors: list[str], paysage_ids: list[str]
) -> dict[tuple[str, str], int]:
    """Renvoie les structures en base reconnues par ces ROR ou ces identifiants Paysage (`api_ids.scanr_patents`), par `("ror", valeur)` ou `("paysage", valeur)`."""
    rows = conn.execute(
        text(f"""
            SELECT 'ror' AS id_type, s.ror_id AS value, s.id
            FROM structures s WHERE s.ror_id = ANY(:rors)
            UNION ALL
            SELECT 'paysage', p.value, s.id
            FROM structures s
            CROSS JOIN LATERAL jsonb_array_elements_text(s.api_ids -> '{Source.SCANR_PATENTS.value}') p(value)
            WHERE p.value = ANY(:paysage)
        """),  # noqa: S608 — source choisie par le code
        {"rors": rors, "paysage": paysage_ids},
    ).all()
    return {(r.id_type, r.value): r.id for r in rows}


def _patent_application(extra: Mapping[str, JsonValue]) -> PatentApplication:
    """Renvoie une demande de `source_extras.patent_applications`, avec sa recherche Espacenet quand elle est publiée."""
    application = PatentApplication.model_validate(extra)
    if application.office and application.publication_number:
        application.espacenet_url = espacenet_url(
            application.office, application.publication_number
        )
    return application


def get_patent_meta(conn: Connection, source_extras: dict[str, JsonValue]) -> PatentMeta:
    """Renvoie les demandes, les déposants et la classification CPC d'un brevet, d'après le `source_extras` de sa publication. Un déposant est rattaché à une structure en base par son ROR, à défaut par son identifiant Paysage."""
    applicants = [
        as_mapping(a) for a in as_sequence(source_extras.get(SourceExtra.PATENT_APPLICANTS))
    ]
    ids = [as_mapping(a.get("ids")) for a in applicants]
    rors = sorted({v for i in ids for v in as_sequence(i.get("ror")) if isinstance(v, str)})
    paysage_ids = sorted(
        {v for i in ids for v in as_sequence(i.get("paysage")) if isinstance(v, str)}
    )
    known = _applicant_structures(conn, rors, paysage_ids) if rors or paysage_ids else {}

    def structure_id(applicant_ids: Mapping[str, JsonValue]) -> int | None:
        for id_type in ("ror", "paysage"):
            for value in as_sequence(applicant_ids.get(id_type)):
                if isinstance(value, str) and (id_type, value) in known:
                    return known[(id_type, value)]
        return None

    # ScanR répète un déposant, avec et sans pays : une seule entrée par structure, à défaut par nom.
    unique: dict[object, PatentApplicant] = {}
    for a, applicant_ids in zip(applicants, ids, strict=True):
        applicant = PatentApplicant(
            name=as_str(a.get("name")),
            type=as_str(a.get("type")),
            country=as_str(a.get("country")),
            structure_id=structure_id(applicant_ids),
        )
        key = applicant.structure_id or (applicant.name or "").casefold()
        if key not in unique or (unique[key].country is None and applicant.country):
            unique[key] = applicant

    applications = [
        _patent_application(as_mapping(a))
        for a in as_sequence(source_extras.get(SourceExtra.PATENT_APPLICATIONS))
    ]
    return PatentMeta(
        applications=sorted(
            applications, key=lambda a: (a.application_date or "", a.publication_date or "")
        ),
        applicants=list(unique.values()),
        cpc=[
            CpcCode.model_validate(as_mapping(c))
            for c in as_sequence(source_extras.get(SourceExtra.CPC))
        ],
        grant_date=as_str(source_extras.get(SourceExtra.PATENT_GRANT_DATE)),
    )


def get_publication_external_identifiers(
    conn: Connection, publication_id: int
) -> list[ExternalIdentifierOut]:
    """Renvoie les PMID et NNT actifs des enregistrements sources de la publication, sans doublon, par type (`_EXTERNAL_IDENTIFIER_TYPES`) puis par valeur.

    Un NNT déjà présent dans une source `theses` est omis : l'identifiant natif de cette source est le NNT, et son lien theses.fr le couvre, comme le lien HAL couvre le `hal_id`.
    """
    rows = conn.execute(
        text("""
            SELECT DISTINCT i.id_type::text AS id_type, i.id_value
            FROM source_records sr
            JOIN source_record_identifiers i ON i.source_record_id = sr.id
            WHERE sr.publication_id = :pid AND i.removed_by IS NULL
              AND i.id_type::text = ANY(:types)
              AND NOT EXISTS (
                  SELECT 1 FROM source_records t
                  WHERE t.publication_id = sr.publication_id AND t.source = 'theses'
                    AND i.id_type = 'nnt' AND t.source_id = i.id_value
              )
        """),
        {"pid": publication_id, "types": [str(t) for t in _EXTERNAL_IDENTIFIER_TYPES]},
    ).all()
    order = [str(t) for t in _EXTERNAL_IDENTIFIER_TYPES]
    return [
        ExternalIdentifierOut(type=r.id_type, value=r.id_value)
        for r in sorted(rows, key=lambda r: (order.index(r.id_type), r.id_value))
    ]


def get_publication_subjects(conn: Connection, publication_id: int) -> list[SubjectOut]:
    """Renvoie les sujets d'une publication, sans doublon, avec leurs sources, triés par libellé sans égard à la casse."""
    rows = conn.execute(
        text("""
            SELECT s.id, s.label, s.label_normalized, s.vocabulary::text AS vocabulary, s.level,
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
        SubjectOut(
            id=r.id,
            label=r.label,
            label_normalized=r.label_normalized,
            vocabulary=r.vocabulary,
            level=r.level,
            sources=r.sources,
        )
        for r in rows
    ]


class PublicationDetailQueries:
    _conn: Connection

    def get_publication_detail(self, publication_id: int) -> PublicationDetailResponse | None:
        """Renvoie le détail complet d'une publication : métadonnées, sources, contributions. `None` si la publication n'existe pas."""
        publication_row = self._conn.execute(
            text(f"""
                SELECT p.id, p.title, p.publication_date,
                       p.publication_date_precision::text AS publication_date_precision,
                       p.doi, p.doc_type::text AS doc_type,
                       p.oa_status::text AS oa_status,
                       p.license::text AS license, p.deposit_license::text AS deposit_license,
                       p.best_copy_url,
                       p.language, p.container_title, p.source_extras, d.abstract, d.keywords,
                       j.id AS serial_id, j.title AS journal_title,
                       CASE WHEN j.id IS NOT NULL THEN {active_issns("j.id")} END AS serial_issns,
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
        # Mots-clés libres réunis depuis les sources : hors référentiel `subjects`, renvoyés à part.
        keywords = publication_row.keywords or []

        sources_rows = self._conn.execute(
            text(f"""
                SELECT sr.source, sr.source_id, {source_record_doi_sql("sr")} AS doi,
                       sr.hal_collections, sr.countries
                FROM source_records sr
                WHERE sr.publication_id = :pid
                ORDER BY sr.created_at DESC
            """),
            {"pid": publication_id},
        ).all()
        sources = [
            SourceRecordOut(
                source=r.source,
                source_id=r.source_id,
                doi=r.doi,
                hal_collections=r.hal_collections,
                countries=r.countries,
            )
            for r in sources_rows
        ]

        auth_rows = self._conn.execute(
            text(f"""
                SELECT a.reference_position AS author_position, a.in_perimeter,
                       a.author_positions::text[] AS author_positions,
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
                author_positions=r.author_positions,
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

        theses_rows = self._conn.execute(
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
            extras_row = self._conn.execute(
                text(f"""
                    SELECT sr.source_extras AS source_record_extras,
                           (SELECT s.label
                            FROM source_record_subjects srs
                            JOIN subjects s ON s.id = srs.subject_id
                            WHERE srs.source_record_id = sr.id
                              AND s.vocabulary = '{SubjectVocabulary.THESES_DISCIPLINE.value}'
                            LIMIT 1) AS discipline,
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

        patent_meta = (
            get_patent_meta(self._conn, publication_row.source_extras or {})
            if publication_row.doc_type == DocType.PATENT
            else None
        )

        subjects = get_publication_subjects(self._conn, publication_id)
        relations = get_publication_relations(self._conn, publication_id)
        external_identifiers = get_publication_external_identifiers(self._conn, publication_id)
        publication_access = access(
            publication_copies(self._conn, [publication_id]).get(publication_id, []),
            doi=publication_row.doi,
        )

        structure_ids = {sid for a in contributions for sid in a.structure_ids or []}
        if patent_meta:
            structure_ids |= {
                a.structure_id for a in patent_meta.applicants if a.structure_id is not None
            }
        structures = structures_by_id(self._conn, structure_ids)

        return PublicationDetailResponse(
            publication=PublicationDetailCore(
                id=publication_row.id,
                title=publication_row.title,
                publication_date=publication_row.publication_date,
                publication_date_precision=publication_row.publication_date_precision,
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
            patent_meta=patent_meta,
            structures=structures,
            subjects=subjects,
            keywords=keywords,
            relations=relations,
            access_url=access_url(
                publication_row.best_copy_url,
                oa_status=publication_row.oa_status,
                doi=publication_row.doi,
            ),
            access=[
                AccessLinkOut(label=a.label, url=a.url, icon=a.icon)
                for a in publication_access.links
            ],
            referenced_by=_referenced_by(sources, publication_access),
            external_identifiers=external_identifiers,
        )
