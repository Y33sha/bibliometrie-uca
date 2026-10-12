"""Normalisation des données theses.fr : staging → tables structurées.

Particularités theses.fr :
- Les personnes liées aux thèses peuvent avoir différent rôles : auteur, directeur, rapporteur, examinateur, président de jury
- Le PPN IdRef sert de clé de déduplication pour les auteurs
- Le NNT sert d'identifiant pour les thèses soutenues
- Les thèses en cours n'ont ni NNT ni DOI
"""

import logging
from collections.abc import Mapping

from sqlalchemy import Connection

from domain.dates import french_date_to_iso
from domain.publications.authorship_roles import THESES_FIELD_ROLES
from domain.publications.identifiers import clean_doi, normalize_nnt
from domain.source_publications.external_ids import ExternalIdType
from domain.sources.theses import (
    aggregate_thesis_persons,
    derive_theses_doc_type,
)
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.sources.normalize import SourceNormalizer
from pipeline.sources.pub_metadata import PublicationMetadata
from pipeline.sources.signature_queries import AuthorshipsBatchQueries
from pipeline.sources.signatures import (
    AddressRecord,
    AuthorBlock,
    AuthorRecord,
    SignatureSyncSettings,
    sync_source_authorships,
)
from pipeline.sources.source_publications import (
    SourcePublicationQueries,
    SourcePublicationUpsert,
)
from pipeline.sources.staging import StagingQueries, StagingRow

# =============================================================
# PUBLICATIONS
# =============================================================


def extract_pub_metadata(these: Mapping[str, JsonValue]) -> PublicationMetadata:
    """Extrait les métadonnées canoniques d'une thèse."""
    title = as_str(these.get("titrePrincipal"))
    date_soutenance = french_date_to_iso(as_str(these.get("dateSoutenance")))
    date_inscription = french_date_to_iso(as_str(these.get("datePremiereInscriptionDoctorat")))

    # pub_year = soutenance > première inscription (cascade theses.fr)
    year_source = date_soutenance or date_inscription
    pub_year = int(year_source[:4]) if year_source else None

    doi = clean_doi(as_str(these.get("doi")))
    nnt_clean = normalize_nnt(as_str(these.get("nnt")))

    return PublicationMetadata(
        title=title,
        pub_year=pub_year,
        doc_type=derive_theses_doc_type(date_soutenance),
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


def _build_source_meta(these: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Construit le meta jsonb pour source_publications à partir des données brutes."""
    meta: dict[str, JsonValue] = {}
    ds = french_date_to_iso(as_str(these.get("dateSoutenance")))
    di = french_date_to_iso(as_str(these.get("datePremiereInscriptionDoctorat")))
    if ds:
        meta["date_soutenance"] = ds
    if di:
        meta["date_inscription"] = di

    discipline = these.get("discipline")
    if discipline:
        meta["discipline"] = discipline

    if etablissement := these.get("etabSoutenanceN"):
        meta["etablissement"] = etablissement

    ecoles = [as_mapping(e) for e in as_sequence(these.get("ecolesDoctorale"))]
    ecoles_clean = [
        {"nom": nom, "ppn": as_str(e.get("ppn"))} for e in ecoles if (nom := as_str(e.get("nom")))
    ]
    if ecoles_clean:
        meta["ecoles_doctorales"] = ecoles_clean

    partenaires = [as_mapping(p) for p in as_sequence(these.get("partenairesDeRecherche"))]
    partenaires_clean = [
        {"nom": nom, "type": as_str(p.get("type"))}
        for p in partenaires
        if (nom := as_str(p.get("nom")))
    ]
    if partenaires_clean:
        meta["partenaires"] = partenaires_clean

    return meta or None


def insert_source_document(
    conn: Connection,
    queries: SourcePublicationQueries,
    these: Mapping[str, JsonValue],
    staging_id: int,
    theses_id: str,
    pub_meta: PublicationMetadata,
) -> int:
    """Crée/retrouve l'entrée source_publications pour theses.fr.

    Les métadonnées canoniques (titre, doc_type, pub_year, doi, nnt, journal, oa_status, language, container_title) viennent toutes de `pub_meta`, construit en amont par `extract_pub_metadata`. `these` ne sert ici que pour les champs propres aux thèses (sujets, sujetsRameau, discipline, écoles doctorales, partenaires, dates).
    """
    nnt = pub_meta.nnt
    external_ids: dict[str, JsonValue] | None = {ExternalIdType.NNT: nnt} if nnt else None

    # Keywords : sujets (mots-clés auteur)
    sujets = as_sequence(these.get("sujets"))
    keywords = [
        libelle for s in sujets if (libelle := as_str(as_mapping(s).get("libelle")))
    ] or None

    # Topics : discipline + sujets Rameau
    topics: dict[str, JsonValue] = {}
    discipline = as_str(these.get("discipline"))
    if discipline:
        topics["discipline"] = discipline
    rameau = as_sequence(these.get("sujetsRameau"))
    rameau_list = [libelle for r in rameau if (libelle := as_str(as_mapping(r).get("libelle")))]
    if rameau_list:
        topics["rameau"] = rameau_list
    topics_json = topics if topics else None

    # Meta spécifique thèse (discipline, écoles doctorales, partenaires, dates)
    source_meta = _build_source_meta(these)
    source_meta_json = source_meta if source_meta else None

    return queries.upsert_source_publication(
        conn,
        SourcePublicationUpsert(
            source="theses",
            source_id=theses_id,
            staging_id=staging_id,
            doi=pub_meta.doi,
            external_ids=external_ids,
            title=pub_meta.title or "",
            pub_year=pub_meta.pub_year,
            doc_type=pub_meta.doc_type,
            journal_id=pub_meta.journal_id,
            container_title=pub_meta.container_title,
            language=pub_meta.language,
            keywords=keywords,
            topics=topics_json,
            oa_status=pub_meta.oa_status,
            meta=source_meta_json,
        ),
    )


# =============================================================
# SOURCE AUTHORSHIPS
# =============================================================


# Champs du payload dont dépendent les signatures : les personnes, par rôle, et les adresses du document.
_AUTHOR_BLOCK_FIELDS = (*THESES_FIELD_ROLES, "partenairesDeRecherche", "etabSoutenanceN")


def extract_theses_author_block(these: Mapping[str, JsonValue]) -> AuthorBlock:
    """Bloc auteurs d'une thèse : les personnes de chaque rôle, et les adresses du document."""
    return {field: these.get(field) for field in _AUTHOR_BLOCK_FIELDS}


def build_theses_author_records(block: AuthorBlock) -> list[AuthorRecord]:
    """Une signature par personne de la thèse, rôles fusionnés (`aggregate_thesis_persons`) ; seuls les auteurs ont une position.

    Toutes les signatures reçoivent les adresses du document : laboratoires partenaires et établissement de soutenance. Ce dernier rattache la thèse au périmètre — theses.fr ne donne pas d'adresses par personne, et les laboratoires partenaires ne sont pas toujours des structures du périmètre.
    """
    partenaires = as_sequence(block.get("partenairesDeRecherche"))
    addr_parts = [nom for p in partenaires if (nom := as_str(as_mapping(p).get("nom")))]
    if etablissement := as_str(block.get("etabSoutenanceN")):
        addr_parts.append(etablissement)
    return [
        AuthorRecord(
            position=a.author_position,
            name=a.name,
            roles=a.roles,
            person_identifiers=dict(a.person_identifiers) if a.person_identifiers else None,
            addresses=[AddressRecord(text=t) for t in addr_parts],
        )
        for a in aggregate_thesis_persons(block)
    ]


def process_authorships(
    conn: Connection,
    these: Mapping[str, JsonValue],
    source_publication_id: int,
    *,
    batch_queries: AuthorshipsBatchQueries,
    sync_settings: SignatureSyncSettings,
) -> None:
    """Synchronise les signatures de la thèse depuis son bloc auteurs."""
    sync_source_authorships(
        conn,
        batch_queries,
        sync_settings,
        "theses",
        source_publication_id,
        extract_theses_author_block(these),
        build_theses_author_records,
    )


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: SourcePublicationQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    staging_queries: StagingQueries,
    batch_queries: AuthorshipsBatchQueries,
    sync_settings: SignatureSyncSettings,
) -> bool:
    """Traite une thèse du staging."""
    staging_id = staging_row.id
    theses_id = staging_row.source_id
    these = staging_row.raw_data

    pub_meta = extract_pub_metadata(these)

    source_publication_id = insert_source_document(
        conn, queries, these, staging_id, theses_id, pub_meta
    )
    process_authorships(
        conn, these, source_publication_id, batch_queries=batch_queries, sync_settings=sync_settings
    )
    staging_queries.mark_done(conn, staging_id)

    return True


class ThesesNormalizer(SourceNormalizer):
    SOURCE = "theses"
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: SourcePublicationQueries,
        batch_queries: AuthorshipsBatchQueries,
        sync_settings: SignatureSyncSettings,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._batch_queries = batch_queries
        self._sync_settings = sync_settings

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        pub_meta = extract_pub_metadata(row.raw_data)
        return pub_meta.title, pub_meta.pub_year

    def normalize_record(self, conn: Connection, row: StagingRow) -> bool | None:
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            staging_queries=self._staging,
            batch_queries=self._batch_queries,
            sync_settings=self._sync_settings,
        )
