"""Router du référentiel des entités organisationnelles et de leurs liens. Sert `/api/structures/*`.

Une structure est un laboratoire, une composante, une université, un centre hospitalier, une école ou un site. La table `structure_relations` en exprime les liens : `est_tutelle_de` pour le rattachement hiérarchique, seul à peser dans la clôture d'un périmètre, et `est_partenaire_de` pour une association sans rattachement. Les formes de nom, qui servent à reconnaître les structures dans les adresses, vivent dans `name_forms.py`.

Les chemins littéraux se déclarent avant `/{structure_id}` : un segment fixe placé après serait capté par le paramètre.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.structures_queries import (
    StructureDetailResponse,
    StructureListItem,
    StructureOut,
    StructuresQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.structure_repository import StructureRepository
from application.services.structures import commands as structure_commands
from interfaces.api.deps import (
    audit_repo,
    db_conn,
    perimeter_repo,
    structure_repo,
    structures_queries,
)
from interfaces.api.models import (
    DeletedResponse,
    RelationCreate,
    StructureCreate,
    StructureRelationCreateResponse,
    StructureUpdate,
)

router = APIRouter(prefix="/api/structures", tags=["structures"])


@router.get("", response_model=list[StructureListItem])
def list_structures(
    type: str | None = Query(None),
    search: str = Query(""),
    queries: StructuresQueries = Depends(structures_queries),
) -> list[StructureListItem]:
    """Liste des structures, filtrable par type et par texte libre.

    `type` : enum `structure_type` (`labo`, `universite`, `onr`, `chu`, `ecole`, `site`, `equipe`, `autre`). `search` : matching accent-insensible sur nom / acronyme / code. Tri canonique par type (labo > universite > onr > chu > ecole > site > autre) puis nom.
    """
    return queries.list_structures(type_filter=type, search=search)


@router.post("", response_model=StructureOut)
def create_structure(
    data: StructureCreate,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> StructureOut:
    """Crée une structure. Lève 409 si le `code` est déjà utilisé."""
    return StructureOut.model_validate(
        structure_commands.create_structure(
            conn,
            code=data.code,
            name=data.name,
            acronym=data.acronym,
            type=data.type,
            ror_id=data.ror_id,
            rnsr_id=data.rnsr_id,
            hal_collection=data.hal_collection,
            api_ids=data.api_ids,
            repo=repo,
            audit_repo=audit,
        )
    )


# ── Relations entre structures ───────────────────────────────────


@router.post("/relations", response_model=StructureRelationCreateResponse)
def create_relation(
    data: RelationCreate,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    perimeter_repo: PerimeterRepository = Depends(perimeter_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> StructureRelationCreateResponse:
    """Crée une relation parent-enfant entre deux structures.

    Idempotent : une relation identique — même parent, même enfant, même type — laisse la table inchangée et rend `{"status": "already_exists"}`.
    """
    row = structure_commands.create_relation(
        conn,
        parent_id=data.parent_id,
        child_id=data.child_id,
        relation_type=data.relation_type,
        repo=repo,
        perimeter_repo=perimeter_repo,
        audit_repo=audit,
    )
    if row is None:
        return StructureRelationCreateResponse.model_validate({"status": "already_exists"})
    return StructureRelationCreateResponse.model_validate(row)


@router.delete("/relations/{relation_id}", response_model=DeletedResponse)
def delete_relation(
    relation_id: int,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    perimeter_repo: PerimeterRepository = Depends(perimeter_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> DeletedResponse:
    """Supprime une relation structure. 404 si l'id n'existe pas."""
    structure_commands.delete_relation(
        conn, relation_id, repo=repo, perimeter_repo=perimeter_repo, audit_repo=audit
    )
    return DeletedResponse()


# ── Une structure ────────────────────────────────────────────────


@router.get("/{structure_id}", response_model=StructureDetailResponse)
def get_structure(
    structure_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> StructureDetailResponse:
    """Détail complet d'une structure : identifiants + parents + enfants + formes de nom.

    Retourne `{structure, parents, children, forms}`. Les parents sont les structures qui ont cette structure comme `child_id` dans `structure_relations` ; les enfants inversement. 404 si la structure n'existe pas.
    """
    detail = queries.get_structure_detail(structure_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Structure introuvable")
    return detail


@router.put("/{structure_id}", response_model=StructureOut)
def update_structure(
    structure_id: int,
    data: StructureUpdate,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> StructureOut:
    """Met à jour une structure, champ par champ.

    Seuls les champs présents dans le corps de la requête sont écrits. Renvoie 404 sur une structure inconnue.
    """
    fields = data.model_dump(exclude_unset=True)
    return StructureOut.model_validate(
        structure_commands.update_structure(
            conn, structure_id, fields=fields, repo=repo, audit_repo=audit
        )
    )


@router.delete("/{structure_id}", response_model=DeletedResponse)
def delete_structure(
    structure_id: int,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    perimeter_repo: PerimeterRepository = Depends(perimeter_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> DeletedResponse:
    """Supprime une structure. Cascade sur les relations et formes de noms liées. 404 si inconnue."""
    structure_commands.delete_structure(
        conn, structure_id, repo=repo, perimeter_repo=perimeter_repo, audit_repo=audit
    )
    return DeletedResponse()
