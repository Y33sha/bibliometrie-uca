"""Router /api/perimeters/* — les ensembles de structures que les phases du pipeline consomment.

Un périmètre (table `perimeters`) nomme des structures racines dans sa colonne `structure_ids`. L'ensemble effectif y ajoute leurs descendants par `est_tutelle_de`, à l'exclusion de `est_partenaire_de` : un partenaire n'entre pas dans le périmètre de sa contrepartie. Cet ensemble est matérialisé dans `perimeter_structures` par `refresh_perimeter_structures` ; les lectures le restituent sans le recalculer.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application.ports.api.perimeters_queries import PerimeterOut, PerimetersAdminQueries
from application.ports.config import ConfigStore
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from application.services.perimeters import commands as perimeter_commands
from interfaces.api.deps import (
    audit_repo,
    config_store,
    db_conn,
    perimeter_repo,
    perimeters_admin_queries,
)
from interfaces.api.models import (
    AddPerimeterStructure,
    CreatedIdResponse,
    OkResponse,
    PerimeterCreate,
    StatusResponse,
)

router = APIRouter()


@router.get("/api/perimeters", response_model=list[PerimeterOut])
def list_perimeters(
    queries: PerimetersAdminQueries = Depends(perimeters_admin_queries),
) -> list[PerimeterOut]:
    """Liste les périmètres avec leurs structures racines.

    `structures` porte les seules racines ; `structure_count` compte l'ensemble effectif, racines et descendants par `est_tutelle_de` réunis.
    """
    return queries.list_perimeters_with_structures()


@router.post("/api/perimeters", response_model=CreatedIdResponse)
def create_perimeter(
    body: PerimeterCreate,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
) -> CreatedIdResponse:
    """Crée un nouveau périmètre, sans structure racine."""
    pid = perimeter_commands.create_perimeter(conn, code=body.code, name=body.name, repo=repo)
    return CreatedIdResponse(id=pid)


@router.put("/api/perimeters/{perimeter_id}", response_model=OkResponse)
def update_perimeter(
    perimeter_id: int,
    body: PerimeterUpdate,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
) -> OkResponse:
    """Met à jour un périmètre (nom, structures racines)."""
    perimeter_commands.update_perimeter(conn, perimeter_id, update=body, repo=repo)
    return OkResponse()


@router.delete("/api/perimeters/{perimeter_id}", response_model=OkResponse)
def delete_perimeter(
    perimeter_id: int,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
    config_repo: ConfigStore = Depends(config_store),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Supprime un périmètre (interdit si utilisé dans la config pipeline)."""
    perimeter_commands.delete_perimeter(
        conn, perimeter_id, repo=repo, config=config_repo, audit_repo=audit
    )
    return OkResponse()


@router.post("/api/perimeters/{perimeter_id}/structures", response_model=StatusResponse)
def add_structure_to_perimeter(
    perimeter_id: int,
    body: AddPerimeterStructure,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
) -> StatusResponse:
    """Ajoute une structure racine au périmètre.

    Renvoie `{"status": "added"}` ou `"already_present"` si la structure était déjà racine.
    """
    outcome = perimeter_commands.add_structure_to_perimeter(
        conn, perimeter_id, body.structure_id, repo=repo
    )
    return StatusResponse(status=outcome)


@router.delete(
    "/api/perimeters/{perimeter_id}/structures/{structure_id}", response_model=StatusResponse
)
def remove_structure_from_perimeter(
    perimeter_id: int,
    structure_id: int,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
) -> StatusResponse:
    """Retire une structure racine du périmètre. N'affecte pas ses sous-structures tant qu'elles sont rattachées à d'autres racines."""
    perimeter_commands.remove_structure_from_perimeter(conn, perimeter_id, structure_id, repo=repo)
    return StatusResponse(status="removed")
