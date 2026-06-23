"""Router /api/admin/duplicates/* (doublons publications)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.publication_duplicates_queries import (
    PubDuplicateNextResponse,
    PublicationDuplicatesQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.publications import (
    mark_distinct as _mark_pubs_distinct,
    merge_publications,
    refresh_from_sources,
)
from interfaces.api.deps import (
    audit_repo_sync,
    db_conn_sync,
    publication_duplicates_queries_sync,
    publication_repo_sync,
)
from interfaces.api.models import (
    MarkDistinctPublications,
    MergePublications,
    OkResponse,
    PubMergeResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/duplicates/next", response_model=PubDuplicateNextResponse)
def next_duplicate_candidate(
    min_title_len: int = Query(30, ge=10),
    offset: int = Query(0, ge=0),
    queries: PublicationDuplicatesQueries = Depends(publication_duplicates_queries_sync),
) -> PubDuplicateNextResponse:
    """Renvoie la paire de publications candidate au dédoublonnage à l'offset donné.

    Les candidats sont produits par la requête `next_pub_duplicate`
    (similarité de titre + proximité pub_year + DOI convergents) ;
    `min_title_len` filtre les titres trop courts pour être
    discriminants. Permet au front d'itérer pair par pair via offset.
    """
    return queries.next_pub_duplicate(min_title_len=min_title_len, offset=offset)


@router.post("/api/admin/duplicates/merge", response_model=PubMergeResponse)
def merge_duplicate_publications(
    body: MergePublications,
    conn: Connection = Depends(db_conn_sync),
    queries: PublicationDuplicatesQueries = Depends(publication_duplicates_queries_sync),
    repo: PublicationRepository = Depends(publication_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> PubMergeResponse:
    """Fusionne deux publications doublons.

    La cible survivante est choisie implicitement (le plus petit id) : côté
    publications, la direction de fusion n'a aucun effet durable, car
    `refresh_from_sources` re-dérive *toutes* les métadonnées canoniques depuis
    l'union des `source_publications` — union identique quel que soit le sens.
    (À l'inverse des personnes, dont le nom du côté gardé survit.) Le refresh
    immédiat fait converger la publication vers son état canonique sans attendre
    un run du pipeline.

    Authorships, sources, adresses et métadonnées sont transférés vers la cible ;
    la source est supprimée. Encadrée par un SAVEPOINT : un échec rollback la
    fusion sans impacter la transaction englobante. 400 si les ids sont égaux,
    404 si une des publications est introuvable.
    """
    if body.pub_id_a == body.pub_id_b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b doivent être différents")

    found = queries.existing_publication_ids((body.pub_id_a, body.pub_id_b))
    if body.pub_id_a not in found or body.pub_id_b not in found:
        raise HTTPException(status_code=404, detail="Publication introuvable")

    target_id, source_id = sorted((body.pub_id_a, body.pub_id_b))

    savepoint = conn.begin_nested()
    try:
        merge_publications(target_id, source_id, repo=repo, audit_repo=audit)
        refresh_from_sources(target_id, repo=repo, audit_repo=audit)
        savepoint.commit()
    except Exception as e:
        savepoint.rollback()
        raise HTTPException(status_code=500, detail=f"Échec de la fusion : {e}") from e

    return PubMergeResponse(ok=True, target_id=target_id, source_id=source_id)


@router.post("/api/admin/duplicates/mark-distinct", response_model=OkResponse)
def mark_publications_distinct(
    body: MarkDistinctPublications,
    repo: PublicationRepository = Depends(publication_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> OkResponse:
    """Marque deux publications comme distinctes (non-doublon confirmé).

    Persiste l'annotation dans `publication_distinctions` : la paire
    ne sera plus proposée par `/duplicates/next` lors des prochaines
    revues. 400 si `pub_id_a == pub_id_b`.
    """
    if body.pub_id_a == body.pub_id_b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b doivent être différents")
    _mark_pubs_distinct(body.pub_id_a, body.pub_id_b, repo=repo, audit_repo=audit)
    return OkResponse()
