"""Router /api/admin/duplicates/* (doublons publications)."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from application.ports.publication_duplicates_queries import AsyncPublicationDuplicatesQueries
from application.publications import async_merge_publications
from application.publications import mark_distinct as _mark_pubs_distinct
from domain.ports.publication_repository import AsyncPublicationRepository
from interfaces.api.async_deps import (
    db_conn,
    publication_duplicates_queries,
    publication_repo,
)
from interfaces.api.models import (
    MarkDistinctPublications,
    MergePublications,
    OkResponse,
    PubDuplicateNextResponse,
    PubMergeResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/duplicates/next", response_model=PubDuplicateNextResponse)
async def next_duplicate_candidate(
    min_title_len: int = Query(30, ge=10),
    offset: int = Query(0, ge=0),
    queries: AsyncPublicationDuplicatesQueries = Depends(publication_duplicates_queries),
) -> Any:
    """Renvoie la paire de publications candidate au dédoublonnage à l'offset donné.

    Les candidats sont produits par la requête `next_pub_duplicate`
    (similarité de titre + proximité pub_year + DOI convergents) ;
    `min_title_len` filtre les titres trop courts pour être
    discriminants. Permet au front d'itérer pair par pair via offset.
    """
    return await queries.next_pub_duplicate(min_title_len=min_title_len, offset=offset)


@router.post("/api/admin/duplicates/merge", response_model=PubMergeResponse)
async def merge_duplicate_publications(
    body: MergePublications,
    conn: AsyncConnection = Depends(db_conn),
    queries: AsyncPublicationDuplicatesQueries = Depends(publication_duplicates_queries),
    repo: AsyncPublicationRepository = Depends(publication_repo),
) -> Any:
    """Fusionne la publication `source_id` dans `target_id`.

    Les authorships, sources, adresses et métadonnées de la source
    sont transférées à la cible ; la source est supprimée.
    Encadrée par un SAVEPOINT : un échec rollback la fusion sans
    impacter la transaction englobante. 400 si les ids sont égaux,
    404 si une des publications est introuvable.
    """
    if body.target_id == body.source_id:
        raise HTTPException(
            status_code=400, detail="target_id et source_id doivent être différents"
        )

    pubs = await queries.get_publications_basic([body.target_id, body.source_id])
    if body.target_id not in pubs or body.source_id not in pubs:
        raise HTTPException(status_code=404, detail="Publication introuvable")

    savepoint = await conn.begin_nested()
    try:
        await async_merge_publications(conn, body.target_id, body.source_id, repo=repo)
        await savepoint.commit()
    except Exception as e:
        await savepoint.rollback()
        raise HTTPException(status_code=500, detail=f"Échec de la fusion : {e}") from e

    return {"ok": True, "target_id": body.target_id, "source_id": body.source_id}


@router.post("/api/admin/duplicates/mark-distinct", response_model=OkResponse)
async def mark_publications_distinct(
    body: MarkDistinctPublications,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPublicationRepository = Depends(publication_repo),
) -> Any:
    """Marque deux publications comme distinctes (non-doublon confirmé).

    Persiste l'annotation dans `publication_distinctions` : la paire
    ne sera plus proposée par `/duplicates/next` lors des prochaines
    revues. 400 si `pub_id_a == pub_id_b`.
    """
    if body.pub_id_a == body.pub_id_b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b doivent être différents")
    await _mark_pubs_distinct(conn, body.pub_id_a, body.pub_id_b, repo=repo)
    return {"ok": True}
