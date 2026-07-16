"""Router Éditeurs — liste, recherche, fusion, types."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.publishers_queries import (
    PublisherDashboardResponse,
    PublisherDetailResponse,
    PublisherListResponse,
    PublisherQueries,
    PublishersFacetsResponse,
)
from application.ports.api.subjects_queries import SubjectFrequency
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.services.publishers import commands as publisher_commands
from domain.publishers.publisher import PUBLISHER_TYPE_LABELS_FR, PUBLISHER_TYPES
from interfaces.api.deps import (
    audit_repo,
    db_conn,
    journal_repo,
    metadata_correction_queries,
    publication_repo,
    publisher_queries,
    publisher_repo,
)
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    EnumOption,
    MergeRequest,
    MergeResponse,
    OkResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/publisher-types", response_model=list[EnumOption])
def list_publisher_types() -> list[EnumOption]:
    """Valeurs possibles de l'enum `publisher_type` avec leur label français.

    Source de vérité côté Python : `domain.publishers.publisher.PUBLISHER_TYPES`
    + `PUBLISHER_TYPE_LABELS_FR` (test d'intégration `TestPublisherTypesEnum`
    vérifie la cohérence avec l'enum SQL). Sert à alimenter le dropdown de
    la page admin éditeurs et la colonne « Type » des pages publiques.
    """
    return [EnumOption(value=v, label_fr=PUBLISHER_TYPE_LABELS_FR[v]) for v in PUBLISHER_TYPES]


@router.get("/api/publishers/facets", response_model=PublishersFacetsResponse)
def publishers_facets(
    search: str | None = None,
    publisher_type: str = Query(""),
    country: str = Query(""),
    with_pubs: bool = False,
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublishersFacetsResponse:
    """Comptes par option pour les 3 facettes du listing éditeurs.

    Convention identique à `/api/journals/facets` et
    `/api/publications/facets` : chaque facette exclut sa propre
    dimension de la condition WHERE.
    """
    return queries.publishers_facets(
        search=search,
        publisher_types=parse_str_csv(publisher_type),
        countries=parse_str_csv(country),
        with_pubs=with_pubs,
    )


@router.get("/api/publishers", response_model=PublisherListResponse)
def list_publishers(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    publisher_type: str = Query(""),
    country: str = Query(""),
    with_pubs: bool = False,
    sort: str = "name",
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublisherListResponse:
    """Liste paginée des éditeurs avec comptage revues + publications.

    Filtres :
    - `search` : insensible à la casse sur le nom normalisé, ignorée si
      < 2 caractères.
    - `publisher_type` / `country` : CSV de valeurs (ex. `commercial,learned_society`).
      Vide = pas de filtre. Aligné sur la convention multi-valeurs de
      `/api/journals` et `/api/publications`.
    - `with_pubs` : si true, n'expose que les éditeurs avec au moins 1
      publication rattachée (via leurs revues). Utilisé par la page
      publique /publishers pour masquer les éditeurs orphelins. L'admin
      garde l'option de tout voir (défaut false).

    `sort` : `name` / `-name` / `journals` / `-journals` / `pubs` /
    `-pubs` ; fallback sur `name` si inconnu.
    """
    return queries.list_publishers(
        search=search,
        publisher_types=parse_str_csv(publisher_type),
        countries=parse_str_csv(country),
        with_pubs=with_pubs,
        sort=sort,
        page=page,
        per_page=per_page,
    )


@router.get("/api/publishers/{publisher_id}", response_model=PublisherDetailResponse)
def get_publisher(
    publisher_id: int,
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublisherDetailResponse:
    """Profil complet d'un éditeur pour la page publique `/publishers/[id]`.

    Inclut métadonnées + préfixes DOI + nombre de revues et publications
    rattachées. 404 si l'éditeur est inconnu.
    """
    row = queries.get_publisher_detail(publisher_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Éditeur introuvable")
    return row


@router.get("/api/publishers/{publisher_id}/dashboard", response_model=PublisherDashboardResponse)
def get_publisher_dashboard(
    publisher_id: int,
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublisherDashboardResponse:
    """Agrégats pour l'onglet « Dashboard » de la page éditeur.

    Distribution des `journal_type` du portfolio + distributions `doc_type` /
    `oa_status` des publications rattachées via les revues. 404 si l'éditeur
    est inconnu.
    """
    result = queries.get_publisher_dashboard(publisher_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Éditeur introuvable")
    return result


@router.get("/api/publishers/{publisher_id}/subjects", response_model=list[SubjectFrequency])
def get_publisher_subjects(
    publisher_id: int,
    limit: int = Query(30, ge=1, le=200),
    queries: PublisherQueries = Depends(publisher_queries),
) -> list[SubjectFrequency]:
    """Top sujets des publications de l'éditeur (pour l'onglet Dashboard).

    Exclut les sujets génériques (`usage_count > 5000`). Retourne une liste
    vide si l'éditeur existe sans publications taggées.
    """
    return queries.get_publisher_subjects(publisher_id, limit=limit)


@router.put("/api/publishers/{publisher_id}", response_model=OkResponse)
def update_publisher(
    publisher_id: int,
    body: PublisherUpdate,
    conn: Connection = Depends(db_conn),
    repo: PublisherRepository = Depends(publisher_repo),
) -> OkResponse:
    """Met à jour un éditeur (modification sélective des champs fournis).

    Seuls les champs explicitement présents dans le body sont écrits
    (`exclude_unset=True`). Lève 404 si l'éditeur n'existe pas.
    """
    publisher_commands.update_publisher(conn, publisher_id, update=body, repo=repo)
    return OkResponse()


@router.post("/api/publishers/{publisher_id}/merge", response_model=MergeResponse)
def merge(
    publisher_id: int,
    body: MergeRequest,
    conn: Connection = Depends(db_conn),
    queries: PublisherQueries = Depends(publisher_queries),
    pub_repo: PublisherRepository = Depends(publisher_repo),
    j_repo: JournalRepository = Depends(journal_repo),
    publication_repo: PublicationRepository = Depends(publication_repo),
    audit: AuditRepository = Depends(audit_repo),
    correction_queries: MetadataCorrectionQueries = Depends(metadata_correction_queries),
) -> MergeResponse:
    """Fusionne l'éditeur `source_id` dans l'éditeur `publisher_id`.

    Les revues et publications rattachées à la source sont transférées à la
    cible ; la source est supprimée. Les journaux à titre partagé sont fusionnés
    (et leurs publications requalifiées contre le `journal_type` cible, cf.
    `merge_journals`). 404 si l'un des deux éditeurs est introuvable.
    """
    found = queries.existing_publisher_ids((publisher_id, body.source_id))
    if publisher_id not in found:
        raise HTTPException(status_code=404, detail="Éditeur cible introuvable")
    if body.source_id not in found:
        raise HTTPException(status_code=404, detail="Éditeur source introuvable")

    publisher_commands.merge_publishers(
        conn,
        publisher_id,
        body.source_id,
        correction_queries=correction_queries,
        publisher_repo=pub_repo,
        journal_repo=j_repo,
        pub_repo=publication_repo,
        audit_repo=audit,
    )
    return MergeResponse(merged=True, source_id=body.source_id, target_id=publisher_id)
