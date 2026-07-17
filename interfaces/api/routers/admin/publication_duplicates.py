"""Router /api/admin/duplicates/* — les doublons de publications : revue, fusion, marquage comme distincts."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.publication_duplicates_queries import (
    PubDuplicateNextResponse,
    PublicationDuplicatesQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.publications import commands as publication_commands
from interfaces.api.deps import (
    audit_repo,
    db_conn,
    publication_duplicates_queries,
    publication_repo,
)
from interfaces.api.models import (
    MarkDistinctPublications,
    MergePublications,
    OkResponse,
    PublicationMergeResponse,
)

router = APIRouter()


@router.get("/api/admin/duplicates/next", response_model=PubDuplicateNextResponse)
def next_duplicate_candidate(
    min_title_len: int = Query(30, ge=10),
    offset: int = Query(0, ge=0),
    queries: PublicationDuplicatesQueries = Depends(publication_duplicates_queries),
) -> PubDuplicateNextResponse:
    """Paire de publications candidate au dédoublonnage, à l'offset donné.

    Les candidats viennent de la requête `next_pub_duplicate`, qui rapproche les titres semblables, les années de publication voisines et les DOI convergents. `min_title_len` écarte les titres trop courts pour discriminer. L'offset laisse l'interface avancer paire par paire.
    """
    return queries.next_pub_duplicate(min_title_len=min_title_len, offset=offset)


@router.post("/api/admin/duplicates/merge", response_model=PublicationMergeResponse)
def merge_duplicate_publications(
    body: MergePublications,
    conn: Connection = Depends(db_conn),
    queries: PublicationDuplicatesQueries = Depends(publication_duplicates_queries),
    repo: PublicationRepository = Depends(publication_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> PublicationMergeResponse:
    """Fusionne deux publications doublons.

    La cible est le plus petit des deux identifiants. Le sens de la fusion est sans portée durable : `refresh_from_sources` re-dérive toutes les métadonnées canoniques depuis l'union des `source_publications`, et cette union est la même dans un sens comme dans l'autre. Le rafraîchissement immédiat porte la publication à son état canonique sans attendre un run du pipeline.

    Les signatures, les sources, les adresses et les métadonnées passent à la cible, puis la source est supprimée. La fusion et le rafraîchissement forment une seule transaction, tenue par le command handler : un échec devient un 500 et annule l'ensemble, sans état intermédiaire. Renvoie 400 sur deux identifiants égaux, 404 sur une publication introuvable.
    """
    if body.pub_id_a == body.pub_id_b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b doivent être différents")

    found = queries.existing_publication_ids((body.pub_id_a, body.pub_id_b))
    if body.pub_id_a not in found or body.pub_id_b not in found:
        raise HTTPException(status_code=404, detail="Publication introuvable")

    target_id, source_id = sorted((body.pub_id_a, body.pub_id_b))

    try:
        publication_commands.merge_publications(
            conn, target_id, source_id, repo=repo, audit_repo=audit
        )
    except Exception as e:
        # Le command handler n'a pas committé ; db_conn rollback sur l'exception
        # propagée. On mappe en 500 sans exposer un état partiel.
        raise HTTPException(status_code=500, detail=f"Échec de la fusion : {e}") from e

    return PublicationMergeResponse(ok=True, target_id=target_id, source_id=source_id)


@router.post("/api/admin/duplicates/mark-distinct", response_model=OkResponse)
def mark_publications_distinct(
    body: MarkDistinctPublications,
    conn: Connection = Depends(db_conn),
    repo: PublicationRepository = Depends(publication_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Marque deux publications comme distinctes (non-doublon confirmé).

    Persiste l'annotation dans `distinct_publications` : la paire est écartée des prochaines revues de `/duplicates/next`. 400 si `pub_id_a == pub_id_b`.
    """
    if body.pub_id_a == body.pub_id_b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b doivent être différents")
    publication_commands.mark_distinct(
        conn, body.pub_id_a, body.pub_id_b, repo=repo, audit_repo=audit
    )
    return OkResponse()
