"""Normalisation des enregistrements sources theses.fr.

Une thèse soutenue a pour identifiant son NNT ; une thèse en cours est sans NNT ni DOI. Les personnes d'une thèse ont un ou plusieurs rôles : auteur, direction, rapport, jury, présidence du jury.
"""

from collections.abc import Mapping

from domain.dates import french_date_to_iso
from domain.publications.contribution_roles import THESES_FIELD_ROLES
from domain.publications.identifiers import clean_doi, normalize_nnt
from domain.publications.metadata import OaStatus
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_mapping, as_sequence, as_str, as_strs
from pipeline.ingestion.common.embargoes import Embargo
from pipeline.ingestion.common.normalizer import Document, SourceNormalizer
from pipeline.ingestion.common.source_contributions import (
    AuthorBlock,
    AuthorRecord,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordUpsert,
)
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.theses.payload import (
    aggregate_thesis_persons,
    derive_theses_doc_type,
    thesis_oa_status,
)
from pipeline.transformation.publishing.find_or_create import Containers


def _defense_date(thesis: Mapping[str, JsonValue]) -> str | None:
    """Renvoie la date de soutenance ISO."""
    return french_date_to_iso(as_str(thesis.get("dateSoutenance")))


def _enrollment_date(thesis: Mapping[str, JsonValue]) -> str | None:
    """Renvoie la date ISO de première inscription en doctorat."""
    return french_date_to_iso(as_str(thesis.get("datePremiereInscriptionDoctorat")))


def get_title(thesis: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le titre principal de la thèse."""
    return as_str(thesis.get("titrePrincipal"))


def get_publication_year(thesis: Mapping[str, JsonValue]) -> int | None:
    """Renvoie l'année de soutenance, à défaut l'année de première inscription."""
    year_source = _defense_date(thesis) or _enrollment_date(thesis)
    return int(year_source[:4]) if year_source else None


def _build_source_extras(thesis: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Renvoie les champs propres à theses.fr, pour `source_records.source_extras`."""
    source_extras: dict[str, JsonValue] = {}
    ds = _defense_date(thesis)
    di = _enrollment_date(thesis)
    if ds:
        source_extras[SourceExtra.DATE_SOUTENANCE] = ds
    if di:
        source_extras[SourceExtra.DATE_INSCRIPTION] = di

    institution = as_mapping(thesis.get("etabSoutenance"))
    if institution_name := as_str(institution.get("nom")):
        source_extras[SourceExtra.ETABLISSEMENT] = institution_name
    if institution_ppn := as_str(institution.get("ppn")):
        source_extras[SourceExtra.ETABLISSEMENT_PPN] = institution_ppn

    doctoral_schools = [as_mapping(e) for e in as_sequence(thesis.get("ecolesDoctorales"))]
    doctoral_schools_clean = [
        {"nom": name, "ppn": as_str(e.get("ppn"))}
        for e in doctoral_schools
        if (name := as_str(e.get("nom")))
    ]
    if doctoral_schools_clean:
        source_extras[SourceExtra.ECOLES_DOCTORALES] = doctoral_schools_clean

    partners = [as_mapping(p) for p in as_sequence(thesis.get("partenairesRecherche"))]
    partners_clean = [
        {"nom": name, "type": as_str(p.get("type")), "ppn": as_str(p.get("ppn")) or None}
        for p in partners
        if (name := as_str(p.get("nom")))
    ]
    if partners_clean:
        source_extras[SourceExtra.PARTENAIRES] = partners_clean

    return source_extras or None


def _subject_labels(subjects: list[Mapping[str, JsonValue]], subject_type: str) -> list[str]:
    """Renvoie les libellés distincts des sujets de type `subject_type`, dans l'ordre."""
    labels = (as_str(s.get("keyword")) for s in subjects if as_str(s.get("type")) == subject_type)
    return list(dict.fromkeys(label for label in labels if label))


def theses_source_record(
    thesis: Mapping[str, JsonValue],
    staging_id: int,
    theses_id: str,
) -> SourceRecordUpsert:
    """Construit l'enregistrement source theses.fr d'une thèse, d'après son détail.

    Sans conteneur. Le type dépend de la présence d'une date de soutenance, le statut open access de la diffusion de la thèse (`thesis_oa_status`). La langue est la première de `langues`, le résumé celui de la première langue pourvue d'un résumé.
    """
    doi = clean_doi(as_str(thesis.get("doi")))
    identifiers: list[SourceIdentifier] = []
    if nnt := normalize_nnt(as_str(thesis.get("nnt"))):
        identifiers.append(
            SourceIdentifier(SourceIdentifierType.NNT, nnt, SourceIdentifierRole.PRIMARY)
        )
    if doi:
        identifiers.append(
            SourceIdentifier(SourceIdentifierType.DOI, doi, SourceIdentifierRole.SECONDARY)
        )

    languages = [lang for lang in as_strs(thesis.get("langues")) if lang]
    # Mots-clés de l'auteur et vedettes RAMEAU, par langue, dans l'ordre de `langues`.
    subjects_by_language = as_mapping(thesis.get("mapSujets"))
    subjects = [
        as_mapping(s)
        for lang in dict.fromkeys([*languages, *subjects_by_language])
        for s in as_sequence(subjects_by_language.get(lang))
    ]
    keywords = _subject_labels(subjects, "sujet") or None

    # Topics : discipline et vedettes RAMEAU.
    topics: dict[str, JsonValue] = {}
    discipline = as_str(thesis.get("discipline"))
    if discipline:
        topics["discipline"] = discipline
    if rameau_list := _subject_labels(subjects, "sujetsRameau"):
        topics["rameau"] = rameau_list
    topics_json = topics if topics else None

    abstracts = as_mapping(thesis.get("resumes"))
    abstract = next(
        (text for lang in [*languages, *abstracts] if (text := as_str(abstracts.get(lang)))),
        None,
    )

    return SourceRecordUpsert(
        source="theses",
        source_id=theses_id,
        staging_id=staging_id,
        identifiers=tuple(identifiers),
        title=get_title(thesis) or "",
        publication_year=get_publication_year(thesis),
        raw_doc_type=derive_theses_doc_type(_defense_date(thesis)),
        serial_id=None,
        monograph_id=None,
        container_title=None,
        raw_language=languages[0] if languages else None,
        abstract=abstract,
        keywords=keywords,
        topics=topics_json,
        oa_status=thesis_oa_status(thesis),
        source_extras=_build_source_extras(thesis),
    )


def extract_theses_author_block(thesis: Mapping[str, JsonValue]) -> AuthorBlock:
    """Renvoie le bloc auteurs d'une thèse : les personnes de chaque rôle."""
    return {field: thesis.get(field) for field in THESES_FIELD_ROLES}


def build_theses_author_records(block: AuthorBlock) -> list[AuthorRecord]:
    """Lit une contribution source par personne de la thèse, rôles fusionnés (`aggregate_thesis_persons`) ; seuls les auteurs ont une position.

    theses.fr est sans adresse par personne. L'établissement de soutenance et les laboratoires partenaires, gardés dans `source_extras` avec leur PPN, rattachent les contributions sources à leurs structures (vue `source_contribution_structures`).
    """
    return [
        AuthorRecord(
            position=a.author_position,
            name=a.name,
            roles=a.roles,
            identifiers=dict(a.identifiers) if a.identifiers else None,
        )
        for a in aggregate_thesis_persons(block)
    ]


class ThesesNormalizer(SourceNormalizer):
    SOURCE = "theses"
    DEFAULT_BATCH_SIZE = 100

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return get_title(row.raw_data), get_publication_year(row.raw_data)

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        """Construit l'enregistrement source de la thèse, sans éditeur ni conteneur."""
        return theses_source_record(doc, row.id, row.source_id)

    def embargo(self, doc: Document) -> Embargo | None:
        """Renvoie un embargo sans date pour une thèse inaccessible destinée à Internet (`thesis_oa_status`)."""
        return Embargo(None) if thesis_oa_status(doc) == OaStatus.EMBARGOED else None

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_theses_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_theses_author_records(block)
