"""Router des formes de nom des structures. Sert `/api/name-forms/*`.

Une forme de nom est une écriture sous laquelle une structure se reconnaît dans le texte brut d'une adresse. La phase `affiliations` les charge toutes et les apparie ; ce router les édite.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Connection

from application.ports.api.structures_queries import NameFormOut, StructuresQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.structure_repository import StructureRepository
from application.services.structures import commands as structure_commands
from interfaces.api.deps import audit_repo, db_conn, structure_repo, structures_queries
from interfaces.api.models import DeletedResponse, NameFormCreate, NameFormUpdate

router = APIRouter(prefix="/api/name-forms", tags=["name-forms"])


@router.post("", response_model=NameFormOut)
def create_name_form(
    data: NameFormCreate,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> NameFormOut:
    """Crée une forme de nom pour une structure, utilisée par le matching d'adresses.

    `form_text` est normalisé (accents, casse, ponctuation) par le service avant insertion. `is_word_boundary` : le match exige une frontière de mot dans l'adresse brute. `is_excluding` : forme dont la présence retire la structure des résultats. `requires_context_of` : liste d'ids de structures qui doivent elles-mêmes matcher l'adresse pour que cette forme active.
    """
    return NameFormOut.model_validate(
        structure_commands.create_name_form(
            conn,
            structure_id=data.structure_id,
            form_text=data.form_text,
            is_word_boundary=data.is_word_boundary,
            is_excluding=data.is_excluding,
            requires_context_of=data.requires_context_of,
            repo=repo,
            audit_repo=audit,
        )
    )


@router.get("/{form_id}", response_model=NameFormOut)
def get_name_form(
    form_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> NameFormOut:
    """Récupère une forme de nom par son id. 404 si inconnue."""
    row = queries.get_name_form(form_id)
    if not row:
        raise HTTPException(status_code=404, detail="Forme de nom introuvable")
    return row


@router.put("/{form_id}", response_model=NameFormOut)
def update_name_form(
    form_id: int,
    data: NameFormUpdate,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> NameFormOut:
    """Met à jour une forme de nom (sélective des champs fournis). 404 si inconnue."""
    fields = data.model_dump(exclude_unset=True)
    return NameFormOut.model_validate(
        structure_commands.update_name_form(
            conn, form_id, fields=fields, repo=repo, audit_repo=audit
        )
    )


@router.delete("/{form_id}", response_model=DeletedResponse)
def delete_name_form(
    form_id: int,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> DeletedResponse:
    """Supprime une forme de nom. 404 si inconnue."""
    structure_commands.delete_name_form(conn, form_id, repo=repo, audit_repo=audit)
    return DeletedResponse()
