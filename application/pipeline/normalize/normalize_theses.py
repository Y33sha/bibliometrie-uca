"""
Normalisation des données theses.fr : staging → tables structurées.

Usage:
    python normalize_theses.py              # traiter tous les works non traités
    python normalize_theses.py --limit 100  # traiter N works (pour test)
    python normalize_theses.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publications                (table de vérité)
    source_publications            (source='theses')
    source_persons              (source='theses')
    source_authorships          (source='theses', avec roles)

Particularités theses.fr :
- Pas de journal (les thèses ne sont pas publiées dans des revues)
- Les rôles sont structurels : auteurs, directeurs, rapporteurs, examinateurs, president
- Le PPN IdRef sert de clé de dédup pour les auteurs
- Le NNT sert de DOI-équivalent pour les thèses soutenues
- Les thèses en cours n'ont ni NNT ni DOI

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Row

from application.pipeline.normalize.base import SourceNormalizer
from application.ports.address_linker import AddressLinker
from application.ports.normalize_theses import ThesesNormalizeQueries
from application.ports.staging import StagingQueries
from application.publications import (
    find_or_create,
    find_thesis_by_title,
    refresh_from_sources,
    try_merge_by_doi,
)
from domain.dates import french_date_to_iso
from domain.normalize import normalize_name, normalize_text
from domain.persons.creation import should_create_source_person
from domain.ports.publication_repository import PublicationRepository
from domain.publication import normalize_nnt
from domain.sources.theses import (
    aggregate_thesis_persons,
    derive_theses_doc_type,
    thesis_authors_compatible,
)

# =============================================================
# PUBLICATIONS
# =============================================================


def _extract_thesis_author(these: dict) -> tuple[str, str] | None:
    """Extrait (last_name, first_name) normalisés de l'auteur de la thèse."""
    auteurs = these.get("auteurs") or []
    if not auteurs:
        return None
    auteur = auteurs[0]
    ln = normalize_name(auteur.get("nom") or "")
    fn = normalize_name(auteur.get("prenom") or "")
    return (ln, fn) if ln else None


def _thesis_author_compatible(
    conn: Connection, queries: ThesesNormalizeQueries, pub_id: int, author: tuple[str, str]
) -> bool:
    primary = queries.fetch_thesis_primary_author(conn, pub_id)
    return thesis_authors_compatible(primary, author)


def extract_pub_metadata(these: dict) -> dict:
    """Extrait les métadonnées de publication d'une thèse.

    Retourne un dict utilisable par find_or_create et par insert_source_document.
    """
    title = these.get("titrePrincipal")
    date_soutenance = french_date_to_iso(these.get("dateSoutenance"))
    date_inscription = french_date_to_iso(these.get("datePremiereInscriptionDoctorat"))

    # pub_year = soutenance > première inscription (cascade theses.fr)
    year_source = date_soutenance or date_inscription
    pub_year = int(year_source[:4]) if year_source else None

    doi = these.get("doi")
    nnt_clean = normalize_nnt(these.get("nnt"))
    title_norm = normalize_text(title) if title else None

    return dict(
        title=title,
        title_normalized=title_norm,
        pub_year=pub_year,
        doc_type=derive_theses_doc_type(date_soutenance),
        doi=doi,
        nnt=nnt_clean,
        oa_status="closed",
        journal_id=None,
        container_title=None,
        language=None,
    )


def find_publication(
    conn: Connection,
    queries: ThesesNormalizeQueries,
    these: dict,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None.

    Déduplication en 2 étapes :
    1. Par DOI ou NNT (via find_or_create avec allow_create=False)
    2. Par titre normalisé + année + compatibilité auteur (spécifique thèses)
    """
    meta = extract_pub_metadata(these)
    title = meta["title"]
    if not title:
        return None

    pub_year = meta["pub_year"]
    doi = meta["doi"]
    nnt_clean = meta["nnt"]
    doc_type = meta["doc_type"]
    title_norm = meta["title_normalized"]

    # 1. Chercher par DOI ou NNT (sans créer)
    pub_id, _ = find_or_create(
        title=title,
        title_normalized=title_norm,
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt_clean,
        allow_create=False,
        repo=pub_repo,
    )
    if pub_id:
        return pub_id

    # 2. Dédup spécifique thèses : titre + année + auteur compatible
    if pub_year and title_norm:
        candidates = find_thesis_by_title(title_norm, pub_year, repo=pub_repo)
        if candidates:
            author = _extract_thesis_author(these)
            for cand in candidates:
                if not author or _thesis_author_compatible(conn, queries, cand.id, author):
                    # Match trouvé → attribuer le DOI si nécessaire
                    try_merge_by_doi(cand.id, doi, repo=pub_repo)
                    return cand.id

    return None


def _update_thesis_meta(
    conn: Connection, queries: ThesesNormalizeQueries, pub_id: int, these: dict
) -> None:
    """Met à jour publications.meta avec les dates de thèse."""
    meta = {}
    ds = french_date_to_iso(these.get("dateSoutenance"))
    di = french_date_to_iso(these.get("datePremiereInscriptionDoctorat"))
    if ds:
        meta["date_soutenance"] = ds
    if di:
        meta["date_inscription"] = di
    if not meta:
        return
    queries.merge_publication_meta(conn, pub_id, meta)


# =============================================================
# SOURCE DOCUMENTS
# =============================================================


def _build_source_meta(these: dict) -> dict | None:
    """Construit le meta jsonb pour source_publications à partir des données brutes."""
    meta: dict[str, Any] = {}
    ds = french_date_to_iso(these.get("dateSoutenance"))
    di = french_date_to_iso(these.get("datePremiereInscriptionDoctorat"))
    if ds:
        meta["date_soutenance"] = ds
    if di:
        meta["date_inscription"] = di

    discipline = these.get("discipline")
    if discipline:
        meta["discipline"] = discipline

    ecoles = these.get("ecolesDoctorale") or []
    ecoles_clean = [{"nom": e["nom"], "ppn": e.get("ppn")} for e in ecoles if e.get("nom")]
    if ecoles_clean:
        meta["ecoles_doctorales"] = ecoles_clean

    partenaires = these.get("partenairesDeRecherche") or []
    partenaires_clean = [
        {"nom": p["nom"], "type": p.get("type")} for p in partenaires if p.get("nom")
    ]
    if partenaires_clean:
        meta["partenaires"] = partenaires_clean

    return meta or None


def insert_source_document(
    conn: Connection,
    queries: ThesesNormalizeQueries,
    these: dict,
    staging_id: int,
    theses_id: str,
    publication_id: int | None,
    pub_meta: dict,
) -> int:
    """Crée/retrouve l'entrée source_publications pour theses.fr.

    Les métadonnées canoniques (titre, doc_type, pub_year, doi, nnt, journal,
    oa_status, language, container_title) viennent toutes de ``pub_meta``,
    construit en amont par ``extract_pub_metadata``. ``these`` ne sert ici
    que pour les extras theses-spécifiques (sujets, sujetsRameau, discipline,
    écoles doctorales, partenaires, dates).
    """
    nnt = pub_meta["nnt"]
    external_ids = {"nnt": nnt} if nnt else None

    # Keywords : sujets (mots-cles auteur)
    sujets = these.get("sujets") or []
    keywords = [s.get("libelle") for s in sujets if s.get("libelle")] or None

    # Topics : discipline + sujets Rameau
    topics = {}
    discipline = these.get("discipline")
    if discipline:
        topics["discipline"] = discipline
    rameau = these.get("sujetsRameau") or []
    rameau_list = [r.get("libelle") for r in rameau if r.get("libelle")]
    if rameau_list:
        topics["rameau"] = rameau_list
    topics_json = topics if topics else None

    # Meta spécifique thèse (discipline, écoles doctorales, partenaires, dates)
    source_meta = _build_source_meta(these)
    source_meta_json = source_meta if source_meta else None

    return queries.upsert_theses_source_publication(
        conn,
        theses_id=theses_id,
        doi=pub_meta["doi"],
        title=pub_meta["title"] or "",
        pub_year=pub_meta["pub_year"],
        doc_type=pub_meta["doc_type"],
        publication_id=publication_id,
        staging_id=staging_id,
        external_ids=external_ids,
        journal_id=pub_meta["journal_id"],
        oa_status=pub_meta["oa_status"],
        language=pub_meta["language"],
        container_title=pub_meta["container_title"],
        keywords=keywords,
        topics_json=topics_json,
        source_meta_json=source_meta_json,
    )


# =============================================================
# SOURCE AUTHORS
# =============================================================


def upsert_source_author(
    conn: Connection, queries: ThesesNormalizeQueries, person: dict
) -> int | None:
    """Crée un `source_persons` theses uniquement quand un PPN (idref stable)
    est fourni. Sans PPN, retourne None : la `source_authorships` sera
    insérée avec `source_person_id=NULL` (cf. chantier source_persons).
    """
    nom = person.get("nom")
    prenom = person.get("prenom")
    if not nom:
        return None

    ppn = person.get("ppn")
    if not should_create_source_person(source="theses", strong_id_value=ppn):
        return None
    assert isinstance(ppn, str)  # narrowing : garanti par le check ci-dessus

    full_name = f"{prenom} {nom}".strip() if prenom else nom
    return queries.upsert_theses_source_person_by_ppn(conn, ppn=ppn, full_name=full_name)


# =============================================================
# SOURCE AUTHORSHIPS
# =============================================================


def process_persons(
    conn: Connection,
    queries: ThesesNormalizeQueries,
    these: dict,
    source_publication_id: int,
    *,
    address_linker: AddressLinker,
) -> None:
    """Traite tous les rôles d'une thèse (auteurs, directeurs, rapporteurs,
    jury, président) en consommant ``aggregate_thesis_persons`` côté domain
    pour la dédup multi-rôles + fusion + assignation de position."""
    queries.clear_source_authorships_for_publication(conn, source_publication_id)

    authorships = aggregate_thesis_persons(these)

    # Affiliations auteur : partenaires de recherche (labos), partagées
    # par toutes les personnes du document.
    partenaires = these.get("partenairesDeRecherche") or []
    addr_parts = [p["nom"] for p in partenaires if p.get("nom")] or []

    for a in authorships:
        # Avec PPN : crée le source_persons (cas légitime conservé)
        # Sans PPN : source_person_id reste NULL (l'auteur sans idref est
        # déjà désigné par son raw_author_name + author_position).
        source_person_id = upsert_source_author(conn, queries, a.person)
        sa_id = queries.upsert_theses_source_authorship(
            conn,
            source_publication_id=source_publication_id,
            source_person_id=source_person_id,
            author_position=a.author_position,
            roles=a.roles,
            raw_author_name=a.raw_author_name,
            identifiers=a.identifiers if a.identifiers else None,
        )
        if addr_parts:
            address_linker.link(conn, sa_id, addr_parts)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: ThesesNormalizeQueries,
    logger: logging.Logger,
    row: Row[Any],
    *,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
    address_linker: AddressLinker,
) -> bool:
    """Traite une thèse du staging."""
    staging_id = row.id
    theses_id = row.source_id
    these = row.raw_data

    try:
        title = these.get("titrePrincipal")
        if not title:
            logger.warning(f"Thèse {theses_id} sans titre — skip")
            return False

        pub_meta = extract_pub_metadata(these)

        publication_id = queries.get_theses_publication_id(conn, theses_id)
        if not publication_id:
            publication_id = find_publication(conn, queries, these, pub_repo=pub_repo)

        if publication_id:
            publication_id = try_merge_by_doi(publication_id, pub_meta["doi"], repo=pub_repo)

        source_publication_id = insert_source_document(
            conn, queries, these, staging_id, theses_id, publication_id, pub_meta
        )

        process_persons(conn, queries, these, source_publication_id, address_linker=address_linker)

        if publication_id:
            refresh_from_sources(publication_id, repo=pub_repo)
            _update_thesis_meta(conn, queries, publication_id, these)

        staging_queries.mark_done(conn, staging_id)

        return True

    except Exception as e:
        logger.error(f"Erreur sur {theses_id}: {e}")
        raise


class ThesesNormalizer(SourceNormalizer):
    SOURCE = "theses"
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: ThesesNormalizeQueries,
        pub_repo_factory: Callable[[Any], PublicationRepository],
        address_linker: AddressLinker,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._pub_repo_factory = pub_repo_factory
        self._pub_repo: PublicationRepository | None = None
        self._address_linker = address_linker

    def preload_caches(self, conn: Connection) -> None:
        self._pub_repo = self._pub_repo_factory(conn)

    def process_work(self, conn: Connection, row: Row[Any]) -> bool | None:
        assert self._pub_repo is not None
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            pub_repo=self._pub_repo,
            staging_queries=self._staging,
            address_linker=self._address_linker,
        )

    def cleanup(self) -> None:
        self._address_linker.clear_cache()

    def on_error(self) -> None:
        # Le cache peut contenir des address_id insérés dans la transaction
        # qui vient d'être rollbackée — invalide-le pour éviter les FK
        # violations sur les works suivants.
        self._address_linker.clear_cache()

    def summary_stats(self, conn: Connection) -> list[str]:
        return [
            f"  {table} (theses) : {self._queries.count_theses_table(conn, table)}"
            for table in ("source_publications", "source_persons", "source_authorships")
        ]
