"""Normalisation des données theses.fr : staging → tables structurées.

Particularités theses.fr :
- Les personnes liées aux thèses peuvent avoir différent rôles : auteur, directeur, rapporteur, examinateur, président de jury
- Le PPN IdRef sert de clé de déduplication pour les auteurs
- Le NNT sert d'identifiant pour les thèses soutenues
- Les thèses en cours n'ont ni NNT ni DOI
"""

from collections.abc import Mapping

from domain.dates import french_date_to_iso
from domain.publications.contribution_roles import THESES_FIELD_ROLES
from domain.publications.identifiers import clean_doi, normalize_nnt
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.ingestion.common.normalizer import Document, SourceNormalizer
from pipeline.ingestion.common.publication_metadata import PublicationMetadata
from pipeline.ingestion.common.source_contributions import (
    AuthorBlock,
    AuthorRecord,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordUpsert,
)
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.theses.payload import aggregate_thesis_persons, derive_theses_doc_type
from pipeline.transformation.publishing.find_or_create import Containers

# =============================================================
# PUBLICATIONS
# =============================================================


def extract_publication_metadata(thesis: Mapping[str, JsonValue]) -> PublicationMetadata:
    """Extrait les métadonnées canoniques d'une thèse."""
    title = as_str(thesis.get("titrePrincipal"))
    defense_date = french_date_to_iso(as_str(thesis.get("dateSoutenance")))
    enrollment_date = french_date_to_iso(as_str(thesis.get("datePremiereInscriptionDoctorat")))

    # publication_year = soutenance > première inscription (cascade theses.fr)
    year_source = defense_date or enrollment_date
    publication_year = int(year_source[:4]) if year_source else None

    doi = clean_doi(as_str(thesis.get("doi")))
    nnt_clean = normalize_nnt(as_str(thesis.get("nnt")))

    return PublicationMetadata(
        title=title,
        publication_year=publication_year,
        doc_type=derive_theses_doc_type(defense_date),
        doi=doi,
        nnt=nnt_clean,
        oa_status="closed",
        journal_id=None,
        container_title=None,
        language=None,
    )


# =============================================================
# SOURCE DOCUMENTS
# =============================================================


def _build_source_extras(thesis: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Champs propres à theses.fr, pour `source_records.source_extras`."""
    source_extras: dict[str, JsonValue] = {}
    ds = french_date_to_iso(as_str(thesis.get("dateSoutenance")))
    di = french_date_to_iso(as_str(thesis.get("datePremiereInscriptionDoctorat")))
    if ds:
        source_extras[SourceExtra.DATE_SOUTENANCE] = ds
    if di:
        source_extras[SourceExtra.DATE_INSCRIPTION] = di

    discipline = thesis.get("discipline")
    if discipline:
        source_extras[SourceExtra.DISCIPLINE] = discipline

    if institution := thesis.get("etabSoutenanceN"):
        source_extras[SourceExtra.ETABLISSEMENT] = institution
    if institution_ppn := as_str(thesis.get("etabSoutenancePpn")):
        source_extras[SourceExtra.ETABLISSEMENT_PPN] = institution_ppn

    doctoral_schools = [as_mapping(e) for e in as_sequence(thesis.get("ecolesDoctorale"))]
    doctoral_schools_clean = [
        {"nom": name, "ppn": as_str(e.get("ppn"))}
        for e in doctoral_schools
        if (name := as_str(e.get("nom")))
    ]
    if doctoral_schools_clean:
        source_extras[SourceExtra.ECOLES_DOCTORALES] = doctoral_schools_clean

    partners = [as_mapping(p) for p in as_sequence(thesis.get("partenairesDeRecherche"))]
    partners_clean = [
        {"nom": name, "type": as_str(p.get("type")), "ppn": as_str(p.get("ppn")) or None}
        for p in partners
        if (name := as_str(p.get("nom")))
    ]
    if partners_clean:
        source_extras[SourceExtra.PARTENAIRES] = partners_clean

    return source_extras or None


def theses_source_record(
    thesis: Mapping[str, JsonValue],
    staging_id: int,
    theses_id: str,
    publication_meta: PublicationMetadata,
) -> SourceRecordUpsert:
    """Enregistrement source theses.fr d'une thèse.

    Les métadonnées canoniques (titre, doc_type, publication_year, doi, nnt, journal, oa_status, language, container_title) viennent de `publication_meta` (`extract_publication_metadata`). `thesis` donne les champs propres aux thèses (sujets, sujetsRameau, discipline, écoles doctorales, partenaires, dates).
    """
    nnt = publication_meta.nnt
    external_ids: dict[str, JsonValue] | None = {ExternalIdType.NNT: nnt} if nnt else None

    # Keywords : sujets (mots-clés auteur)
    subjects = as_sequence(thesis.get("sujets"))
    keywords = [label for s in subjects if (label := as_str(as_mapping(s).get("libelle")))] or None

    # Topics : discipline + sujets Rameau
    topics: dict[str, JsonValue] = {}
    discipline = as_str(thesis.get("discipline"))
    if discipline:
        topics["discipline"] = discipline
    rameau = as_sequence(thesis.get("sujetsRameau"))
    rameau_list = [label for r in rameau if (label := as_str(as_mapping(r).get("libelle")))]
    if rameau_list:
        topics["rameau"] = rameau_list
    topics_json = topics if topics else None

    return SourceRecordUpsert(
        source="theses",
        source_id=theses_id,
        staging_id=staging_id,
        doi=publication_meta.doi,
        external_ids=external_ids,
        title=publication_meta.title or "",
        publication_year=publication_meta.publication_year,
        raw_doc_type=publication_meta.doc_type,
        journal_id=publication_meta.journal_id,
        container_title=publication_meta.container_title,
        raw_language=publication_meta.language,
        keywords=keywords,
        topics=topics_json,
        oa_status=publication_meta.oa_status,
        source_extras=_build_source_extras(thesis),
    )


# =============================================================
# SOURCE CONTRIBUTIONS
# =============================================================


def extract_theses_author_block(thesis: Mapping[str, JsonValue]) -> AuthorBlock:
    """Bloc auteurs d'une thèse : les personnes de chaque rôle."""
    return {field: thesis.get(field) for field in THESES_FIELD_ROLES}


def build_theses_author_records(block: AuthorBlock) -> list[AuthorRecord]:
    """Une contribution source par personne de la thèse, rôles fusionnés (`aggregate_thesis_persons`) ; seuls les auteurs ont une position.

    theses.fr ne donne pas d'adresse par personne. L'établissement de soutenance et les laboratoires partenaires, gardés dans `source_extras` avec leur PPN, rattachent les contributions sources à leurs structures (vue `source_contribution_structures`).
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
        publication_meta = extract_publication_metadata(row.raw_data)
        return publication_meta.title, publication_meta.publication_year

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        """Une thèse n'a ni éditeur ni conteneur."""
        return theses_source_record(doc, row.id, row.source_id, extract_publication_metadata(doc))

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_theses_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_theses_author_records(block)
