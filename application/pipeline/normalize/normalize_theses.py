"""Normalisation des données theses.fr : staging → tables structurées.

Particularités theses.fr :
- Les personnes liées aux thèses peuvent avoir différent rôles : auteur, directeur, rapporteur, examinateur, président de jury
- Le PPN IdRef sert de clé de déduplication pour les auteurs
- Le NNT sert d'identifiant pour les thèses soutenues
- Les thèses en cours n'ont ni NNT ni DOI
"""

import logging
from collections.abc import Callable, Mapping

from sqlalchemy import Connection

from application.pipeline.normalize._authorships_batch import AddressRecord, write_addresses
from application.pipeline.normalize.base import SourceNormalizer
from application.pipeline.timings import StepTimer
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.source_publications import (
    SourcePublicationQueries,
    SourcePublicationRow,
)
from application.ports.pipeline.normalize.staging import StagingQueries, StagingRow
from application.ports.repositories.publication_repository import PublicationRepository
from domain.dates import french_date_to_iso
from domain.normalize import clean_raw_author_name, normalize_name_form
from domain.publications.identifiers import clean_doi, normalize_nnt
from domain.sources.theses import (
    aggregate_thesis_persons,
    derive_theses_doc_type,
)
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str

# =============================================================
# PUBLICATIONS
# =============================================================


def extract_pub_metadata(these: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Extrait les métadonnées de publication d'une thèse.

    Retourne un dict utilisable par `insert_source_document`.
    """
    title = as_str(these.get("titrePrincipal"))
    date_soutenance = french_date_to_iso(as_str(these.get("dateSoutenance")))
    date_inscription = french_date_to_iso(as_str(these.get("datePremiereInscriptionDoctorat")))

    # pub_year = soutenance > première inscription (cascade theses.fr)
    year_source = date_soutenance or date_inscription
    pub_year = int(year_source[:4]) if year_source else None

    doi = clean_doi(as_str(these.get("doi")))
    nnt_clean = normalize_nnt(as_str(these.get("nnt")))

    return {
        "title": title,
        "pub_year": pub_year,
        "doc_type": derive_theses_doc_type(date_soutenance),
        "doi": doi,
        "nnt": nnt_clean,
        "oa_status": "closed",
        "journal_id": None,
        "container_title": None,
        "language": None,
    }


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
    pub_meta: Mapping[str, JsonValue],
) -> int:
    """Crée/retrouve l'entrée source_publications pour theses.fr.

    Les métadonnées canoniques (titre, doc_type, pub_year, doi, nnt, journal, oa_status, language, container_title) viennent toutes de `pub_meta`, construit en amont par `extract_pub_metadata`. `these` ne sert ici que pour les champs propres aux thèses (sujets, sujetsRameau, discipline, écoles doctorales, partenaires, dates).
    """
    nnt = pub_meta["nnt"]
    external_ids = {"nnt": nnt} if nnt else None

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
        SourcePublicationRow(
            source="theses",
            source_id=theses_id,
            staging_id=staging_id,
            doi=as_str(pub_meta["doi"]),
            external_ids=external_ids,
            title=as_str(pub_meta["title"]) or "",
            pub_year=as_int(pub_meta["pub_year"]),
            doc_type=as_str(pub_meta["doc_type"]),
            journal_id=as_int(pub_meta["journal_id"]),
            container_title=as_str(pub_meta["container_title"]),
            language=as_str(pub_meta["language"]),
            keywords=keywords,
            topics=topics_json,
            oa_status=as_str(pub_meta["oa_status"]),
            meta=source_meta_json,
        ),
    )


# =============================================================
# SOURCE AUTHORSHIPS
# =============================================================


def process_authorships(
    conn: Connection,
    these: Mapping[str, JsonValue],
    source_publication_id: int,
    *,
    batch_queries: AuthorshipsBatchQueries,
) -> None:
    """Traite tous les rôles d'une thèse (auteurs, directeurs, rapporteurs, jury, président) en consommant `aggregate_thesis_persons` côté domain pour la déduplication multi-rôles + fusion + assignation de position."""
    batch_queries.clear_source_authorships_for_publication(conn, source_publication_id)

    authorships = aggregate_thesis_persons(these)

    # Adresses partagées par toutes les personnes du document : laboratoires partenaires + établissement de soutenance.
    # Ce dernier rattache la thèse au périmètre — theses.fr ne porte pas d'adresses, et les laboratoires partenaires ne sont pas toujours des structures du périmètre.
    partenaires = as_sequence(these.get("partenairesDeRecherche"))
    addr_parts = [nom for p in partenaires if (nom := as_str(as_mapping(p).get("nom")))]
    if etablissement := as_str(these.get("etabSoutenanceN")):
        addr_parts.append(etablissement)
    shared_addresses = [AddressRecord(text=t) for t in addr_parts]

    # Signatures insérées une par une (`RETURNING`) : les non-auteurs ont `author_position` NULL, que le remap par position du writer batch ne saurait porter.
    # Les `sa_id` récoltés portent tous les mêmes adresses document, écrites en un seul `write_addresses`.
    sa_addresses: list[tuple[int | None, list[AddressRecord]]] = []
    for a in authorships:
        # Nom nettoyé une fois : sert de nom brut stocké et de base au nom normalisé (clé
        # d'identité), comme sur les autres sources (cf. `_authorships_batch`).
        clean_name = clean_raw_author_name(a.raw_author_name)
        sa_id = batch_queries.upsert_source_authorship(
            conn,
            {
                "source": "theses",
                "source_publication_id": source_publication_id,
                "author_position": a.author_position,
                "author_name_normalized": normalize_name_form(clean_name),
                "is_corresponding": False,
                "roles": a.roles,
                "raw_author_name": clean_name,
                "person_identifiers": a.person_identifiers if a.person_identifiers else None,
            },
        )
        sa_addresses.append((sa_id, shared_addresses))

    if addr_parts:
        write_addresses(conn, batch_queries, sa_addresses)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: SourcePublicationQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    publication_repo: PublicationRepository,
    staging_queries: StagingQueries,
    batch_queries: AuthorshipsBatchQueries,
) -> bool:
    """Traite une thèse du staging."""
    staging_id = staging_row.id
    theses_id = staging_row.source_id
    these = staging_row.raw_data

    title = these.get("titrePrincipal")
    if not title:
        logger.warning("Thèse %s sans titre — ignorée", theses_id)
        staging_queries.mark_done(conn, staging_id)
        return False

    t = StepTimer()
    pub_meta = extract_pub_metadata(these)

    source_publication_id = insert_source_document(
        conn, queries, these, staging_id, theses_id, pub_meta
    )
    t.mark("theses_doc")

    process_authorships(conn, these, source_publication_id, batch_queries=batch_queries)
    t.mark("authorships")

    staging_queries.mark_done(conn, staging_id)
    t.log_if_slow(theses_id, logger)

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
        publication_repo_factory: Callable[[Connection], PublicationRepository],
        batch_queries: AuthorshipsBatchQueries,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._publication_repo_factory = publication_repo_factory
        self._publication_repo: PublicationRepository | None = None
        self._batch_queries = batch_queries

    def preload_caches(self, conn: Connection) -> None:
        self._publication_repo = self._publication_repo_factory(conn)

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        assert self._publication_repo is not None
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            publication_repo=self._publication_repo,
            staging_queries=self._staging,
            batch_queries=self._batch_queries,
        )
