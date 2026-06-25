"""Router périmètres — définition des ensembles de structures UCA.

Un `perimeter` (table `perimeters`) nomme un ensemble de structures racines (colonne `structure_ids`) ; l'ensemble effectif est résolu par la CTE récursive `get_perimeter_structure_ids` (descend est_tutelle_de et est_partenaire_de).
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application.perimeters import commands as perimeter_commands
from application.ports.api.perimeters_queries import PerimeterOut, PerimetersAdminQueries
from application.ports.config import ConfigStore
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from interfaces.api.deps import (
    audit_repo_sync,
    config_store_sync,
    db_conn_sync,
    perimeter_repo_sync,
    perimeters_admin_queries_sync,
)
from interfaces.api.models import (
    AddPerimeterStructure,
    CreatedIdResponse,
    OkResponse,
    PerimeterCreate,
    PerimeterUpdate,
    StatusResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/perimeters", response_model=list[PerimeterOut])
def list_perimeters(
    queries: PerimetersAdminQueries = Depends(perimeters_admin_queries_sync),
) -> list[PerimeterOut]:
    """Liste tous les périmètres avec leurs structures racines résolues.

    Pour chaque périmètre, renvoie les structures racines directes (`structures`) et le décompte total après descente récursive des relations (`structure_count`). Le décompte inclut donc les sous-structures rattachées par `est_tutelle_de` / `est_partenaire_de`.
    """
    return queries.list_perimeters_with_structures()


@router.post("/api/perimeters", response_model=CreatedIdResponse)
def create_perimeter(
    body: PerimeterCreate,
    conn: Connection = Depends(db_conn_sync),
    repo: PerimeterRepository = Depends(perimeter_repo_sync),
) -> CreatedIdResponse:
    """Crée un nouveau périmètre."""
    code = body.code.strip()
    name = body.name.strip()
    description = (body.description or "").strip() or None
    pid = perimeter_commands.create_perimeter(
        conn,
        code=code,
        name=name,
        description=description,
        repo=repo,
    )
    return CreatedIdResponse(id=pid)


@router.put("/api/perimeters/{perimeter_id}", response_model=OkResponse)
def update_perimeter(
    perimeter_id: int,
    body: PerimeterUpdate,
    conn: Connection = Depends(db_conn_sync),
    repo: PerimeterRepository = Depends(perimeter_repo_sync),
) -> OkResponse:
    """Met à jour un périmètre (nom, description, structures)."""
    fields = body.model_dump(exclude_unset=True)
    # Nettoyer : strip des strings et description vide → None
    if "name" in fields and isinstance(fields["name"], str):
        fields["name"] = fields["name"].strip()
    if "description" in fields and isinstance(fields["description"], str):
        fields["description"] = fields["description"].strip() or None
    perimeter_commands.update_perimeter(conn, perimeter_id, fields=fields, repo=repo)
    return OkResponse()


@router.delete("/api/perimeters/{perimeter_id}", response_model=OkResponse)
def delete_perimeter(
    perimeter_id: int,
    conn: Connection = Depends(db_conn_sync),
    repo: PerimeterRepository = Depends(perimeter_repo_sync),
    config_repo: ConfigStore = Depends(config_store_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> OkResponse:
    """Supprime un périmètre (interdit si utilisé dans la config pipeline)."""
    perimeter_commands.delete_perimeter(
        conn, perimeter_id, repo=repo, config=config_repo, audit_repo=audit
    )
    return OkResponse()


@router.post("/api/perimeters/{perimeter_id}/structures", response_model=StatusResponse)
def add_perimeter_structure(
    perimeter_id: int,
    body: AddPerimeterStructure,
    conn: Connection = Depends(db_conn_sync),
    repo: PerimeterRepository = Depends(perimeter_repo_sync),
) -> StatusResponse:
    """Ajoute une structure racine au périmètre.

    Renvoie `{"status": "added"}` ou `"already_present"` si la structure était déjà racine.
    """
    status = perimeter_commands.add_perimeter_structure(
        conn, perimeter_id, body.structure_id, repo=repo
    )
    return StatusResponse(status=status)


@router.delete(
    "/api/perimeters/{perimeter_id}/structures/{structure_id}", response_model=StatusResponse
)
def remove_perimeter_structure(
    perimeter_id: int,
    structure_id: int,
    conn: Connection = Depends(db_conn_sync),
    repo: PerimeterRepository = Depends(perimeter_repo_sync),
) -> StatusResponse:
    """Retire une structure racine du périmètre. N'affecte pas ses sous-structures tant qu'elles sont rattachées à d'autres racines."""
    perimeter_commands.remove_perimeter_structure(conn, perimeter_id, structure_id, repo=repo)
    return StatusResponse(status="removed")
