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

from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb as Json

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
from domain.authorship_roles import THESES_FIELD_ROLES, merge_roles
from domain.normalize import normalize_name, normalize_text
from domain.ports.publication_repository import PublicationRepository
from domain.publication import normalize_nnt
from domain.sources.theses import (
    derive_theses_doc_type,
    extract_thesis_year,
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
    cur: Any, queries: ThesesNormalizeQueries, pub_id: int, author: tuple[str, str]
) -> bool:
    primary = queries.fetch_thesis_primary_author(cur, pub_id)
    return thesis_authors_compatible(primary, author)


def extract_pub_metadata(these: dict) -> dict:
    """Extrait les métadonnées de publication d'une thèse.

    Retourne un dict utilisable par find_or_create et par insert_source_document.
    """
    title = these.get("titrePrincipal")
    doc_type = derive_theses_doc_type(these.get("dateSoutenance"))

    pub_year = extract_thesis_year(
        these.get("dateSoutenance"), these.get("datePremiereInscriptionDoctorat")
    )

    doi = these.get("doi")
    nnt_clean = normalize_nnt(these.get("nnt"))
    title_norm = normalize_text(title) if title else None

    return dict(
        title=title,
        title_normalized=title_norm,
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt_clean,
        oa_status="closed",
        journal_id=None,
        container_title=None,
        language=None,
    )


def find_publication(
    cur: Any,
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
        cur,
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
        candidates = find_thesis_by_title(cur, title_norm, pub_year, repo=pub_repo)
        if candidates:
            author = _extract_thesis_author(these)
            for cand in candidates:
                if not author or _thesis_author_compatible(cur, queries, cand.id, author):
                    # Match trouvé → attribuer le DOI si nécessaire
                    try_merge_by_doi(cur, cand.id, doi, repo=pub_repo)
                    return cand.id

    return None


def _parse_date_iso(date_str: str | None) -> str | None:
    """Convertit JJ/MM/AAAA → YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except (IndexError, ValueError):
        return None


def _update_thesis_meta(
    cur: Any, queries: ThesesNormalizeQueries, pub_id: int, these: dict
) -> None:
    """Met à jour publications.meta avec les dates de thèse."""
    meta = {}
    ds = _parse_date_iso(these.get("dateSoutenance"))
    di = _parse_date_iso(these.get("datePremiereInscriptionDoctorat"))
    if ds:
        meta["date_soutenance"] = ds
    if di:
        meta["date_inscription"] = di
    if not meta:
        return
    queries.merge_publication_meta(cur, pub_id, Json(meta))


# =============================================================
# SOURCE DOCUMENTS
# =============================================================


def _build_source_meta(these: dict) -> dict | None:
    """Construit le meta jsonb pour source_publications à partir des données brutes."""
    meta: dict[str, Any] = {}
    ds = _parse_date_iso(these.get("dateSoutenance"))
    di = _parse_date_iso(these.get("datePremiereInscriptionDoctorat"))
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
    cur: Any,
    queries: ThesesNormalizeQueries,
    these: dict,
    staging_id: int,
    theses_id: str,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    """Crée/retrouve l'entrée source_publications pour theses.fr."""
    title = these.get("titrePrincipal") or ""
    doc_type = derive_theses_doc_type(these.get("dateSoutenance"))

    pub_year = extract_thesis_year(
        these.get("dateSoutenance"), these.get("datePremiereInscriptionDoctorat")
    )

    doi = these.get("doi")
    nnt = normalize_nnt(these.get("nnt"))
    external_ids = Json({"nnt": nnt}) if nnt else None

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
    topics_json = Json(topics) if topics else None

    # Meta spécifique thèse (discipline, écoles doctorales, partenaires, dates)
    source_meta = _build_source_meta(these)
    source_meta_json = Json(source_meta) if source_meta else None

    # Metadonnees de publication (pour creation differee)
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    return queries.upsert_theses_source_publication(
        cur,
        theses_id=theses_id,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=doc_type,
        publication_id=publication_id,
        staging_id=staging_id,
        external_ids=external_ids,
        journal_id=journal_id,
        oa_status=oa_status,
        language=language,
        container_title=container_title,
        keywords=keywords,
        topics_json=topics_json,
        source_meta_json=source_meta_json,
    )


# =============================================================
# SOURCE AUTHORS
# =============================================================


def upsert_source_author(cur: Any, queries: ThesesNormalizeQueries, person: dict) -> int | None:
    """Crée un `source_persons` theses uniquement quand un PPN (idref stable)
    est fourni. Sans PPN, retourne None : la `source_authorships` sera
    insérée avec `source_person_id=NULL` (cf. chantier source_persons).
    """
    nom = person.get("nom")
    prenom = person.get("prenom")
    if not nom:
        return None

    ppn = person.get("ppn")
    if not ppn:
        return None

    full_name = f"{prenom} {nom}".strip() if prenom else nom
    return queries.upsert_theses_source_person_by_ppn(cur, ppn=ppn, full_name=full_name)


# =============================================================
# SOURCE AUTHORSHIPS
# =============================================================


def process_persons(
    cur: Any,
    queries: ThesesNormalizeQueries,
    these: dict,
    source_publication_id: int,
    *,
    address_linker: AddressLinker,
) -> None:
    """Traite tous les rôles d'une thèse : auteurs, directeurs, rapporteurs, etc.

    Une même personne peut apparaître dans plusieurs champs (ex: directeur + jury).
    On regroupe les rôles par personne (via PPN ou nom).
    """
    # Pré-nettoyage : re-traitement → table blanche pour cette publi.
    queries.clear_source_authorships_for_publication(cur, source_publication_id)

    # Collecter tous les (personne, rôles) par clé de dédup
    person_roles: dict[str, dict] = {}  # clé → {"person": dict, "roles": list[str]}

    for field, roles in THESES_FIELD_ROLES.items():
        if field == "president":
            # Champ singulier (pas un array)
            president = these.get("president")
            if president and president.get("nom"):
                persons = [president]
            else:
                continue
        else:
            persons = these.get(field) or []

        for person in persons:
            ppn = person.get("ppn")
            nom = person.get("nom")
            if not nom:
                continue

            key = ppn if ppn else f"name:{nom}:{person.get('prenom', '')}"

            if key not in person_roles:
                person_roles[key] = {"person": person, "roles": []}
            person_roles[key]["roles"].extend(roles)

    # Affiliations auteur : partenaires de recherche (labos)
    partenaires = these.get("partenairesDeRecherche") or []
    addr_parts = [p["nom"] for p in partenaires if p.get("nom")] or []

    # Insérer les authorships avec rôles fusionnés
    position = 0
    for _key, info in person_roles.items():
        person = info["person"]
        nom = person.get("nom")
        if not nom:
            continue

        # Avec PPN : crée le source_persons (cas légitime conservé)
        # Sans PPN : source_person_id reste NULL (l'auteur sans idref est
        # déjà désigné par son raw_author_name + author_position).
        source_person_id = upsert_source_author(cur, queries, person)

        roles = merge_roles([info["roles"]])
        is_author = "author" in roles

        author_full_name = ((person.get("prenom") or "") + " " + nom).strip()

        ppn = person.get("ppn")
        identifiers = Json({"idref": ppn}) if ppn else None

        sa_id = queries.upsert_theses_source_authorship(
            cur,
            source_publication_id=source_publication_id,
            source_person_id=source_person_id,
            author_position=position if is_author else None,
            roles=roles,
            raw_author_name=author_full_name,
            identifiers=identifiers,
        )

        if addr_parts:
            address_linker.link(cur, sa_id, addr_parts)
        if is_author:
            position += 1


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    cur: Any,
    queries: ThesesNormalizeQueries,
    logger: Any,
    row: dict,
    *,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
    address_linker: AddressLinker,
) -> bool:
    """Traite une thèse du staging."""
    staging_id = row["id"]
    theses_id = row["source_id"]
    these = row["raw_data"]

    try:
        title = these.get("titrePrincipal")
        if not title:
            logger.warning(f"Thèse {theses_id} sans titre — skip")
            return False

        pub_meta = extract_pub_metadata(these)

        publication_id = queries.get_theses_publication_id(cur, theses_id)
        if not publication_id:
            publication_id = find_publication(cur, queries, these, pub_repo=pub_repo)

        if publication_id:
            publication_id = try_merge_by_doi(cur, publication_id, pub_meta["doi"], repo=pub_repo)

        source_publication_id = insert_source_document(
            cur, queries, these, staging_id, theses_id, publication_id, pub_meta
        )

        process_persons(cur, queries, these, source_publication_id, address_linker=address_linker)

        if publication_id:
            refresh_from_sources(cur, publication_id, repo=pub_repo)
            _update_thesis_meta(cur, queries, publication_id, these)

        staging_queries.mark_done(cur, staging_id)

        return True

    except Exception as e:
        logger.error(f"Erreur sur {theses_id}: {e}")
        raise


class ThesesNormalizer(SourceNormalizer):
    SOURCE = "theses"
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        conn: Any,
        logger: Any,
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

    def preload_caches(self, cur: Any) -> None:
        self._pub_repo = self._pub_repo_factory(cur)

    def process_work(self, cur: Any, row: Any) -> bool | None:
        assert self._pub_repo is not None
        return process_work(
            cur,
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

    def summary_stats(self, cur: Any) -> list[str]:
        return [
            f"  {table} (theses) : {self._queries.count_theses_table(cur, table)}"
            for table in ("source_publications", "source_persons", "source_authorships")
        ]
