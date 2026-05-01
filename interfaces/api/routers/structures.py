"""Router structures — CRUD structures, relations parent-enfant, formes de noms.

Les structures couvrent les entités organisationnelles (labos, UFR,
universités, CHU, écoles, sites). Les relations `structure_relations`
expriment les tutelles (`est_tutelle_de`, `est_partenaire_de`) et les
formes de nom `structure_name_forms` servent au matching d'adresses
(phase pipeline `addresses`).
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application import structures as structures_service
from infrastructure.db.queries.structures import (
    get_name_form_async,
    get_structure_detail_async,
    list_structures_async,
)
from infrastructure.repositories import async_structure_repository
from interfaces.api.async_deps import get_async_cursor
from interfaces.api.models import (
    DeletedResponse,
    NameFormCreate,
    NameFormOut,
    NameFormUpdate,
    RelationCreate,
    StructureCreate,
    StructureDetailResponse,
    StructureListItem,
    StructureOut,
    StructureRelationCreateResponse,
    StructureUpdate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/structures", response_model=list[StructureListItem])
async def list_structures(
    type: str | None = Query(None),
    search: str = Query(""),
) -> Any:
    """Liste des structures, filtrable par type et par texte libre.

    `type` : enum `structure_type` (`labo`, `universite`, `onr`,
    `chu`, `ecole`, `site`, `equipe`, `autre`). `search` : matching
    accent-insensible sur nom / acronyme / code. Tri canonique par
    type (labo > universite > onr > chu > ecole > site > autre) puis
    nom.
    """
    async with get_async_cursor() as (cur, _conn):
        return await list_structures_async(cur, type_filter=type, search=search)


@router.get("/api/structures/{structure_id}", response_model=StructureDetailResponse)
async def get_structure(structure_id: int) -> Any:
    """Détail complet d'une structure : identifiants + parents + enfants + formes de nom.

    Retourne `{structure, parents, children, forms}`. Les parents
    sont les structures qui ont cette structure comme `child_id`
    dans `structure_relations` ; les enfants inversement. 404 si la
    structure n'existe pas.
    """
    async with get_async_cursor() as (cur, _conn):
        detail = await get_structure_detail_async(cur, structure_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Structure not found")
        return detail


@router.post("/api/structures", response_model=StructureOut)
async def create_structure(data: StructureCreate) -> Any:
    """Crée une structure. Lève 409 si le `code` est déjà utilisé."""
    async with get_async_cursor() as (cur, conn):
        return await structures_service.create_structure(
            cur,
            code=data.code,
            name=data.name,
            acronym=data.acronym,
            type=data.type,
            ror_id=data.ror_id,
            rnsr_id=data.rnsr_id,
            hal_collection=data.hal_collection,
            api_ids=data.api_ids,
            repo=async_structure_repository(cur),
        )


@router.put("/api/structures/{structure_id}", response_model=StructureOut)
async def update_structure(structure_id: int, data: StructureUpdate) -> Any:
    """Met à jour une structure (mise à jour sélective des champs fournis).

    Seuls les champs explicitement présents dans le body sont écrits.
    404 si la structure n'existe pas.
    """
    fields = data.model_dump(exclude_unset=True)
    async with get_async_cursor() as (cur, conn):
        return await structures_service.update_structure(
            cur, structure_id, fields=fields, repo=async_structure_repository(cur)
        )


@router.delete("/api/structures/{structure_id}", response_model=DeletedResponse)
async def delete_structure(structure_id: int) -> Any:
    """Supprime une structure. Cascade sur les relations et formes de
    noms liées. 404 si inconnue."""
    async with get_async_cursor() as (cur, conn):
        await structures_service.delete_structure(
            cur, structure_id, repo=async_structure_repository(cur)
        )
        return {"deleted": True}


@router.post("/api/structure-relations", response_model=StructureRelationCreateResponse)
async def create_relation(data: RelationCreate) -> Any:
    """Crée une relation parent-enfant entre deux structures.

    Idempotent : si une relation identique (même parent, child, type)
    existe, renvoie `{"status": "already_exists"}` au lieu de la
    recréer.
    """
    async with get_async_cursor() as (cur, conn):
        row = await structures_service.create_relation(
            cur,
            parent_id=data.parent_id,
            child_id=data.child_id,
            relation_type=data.relation_type,
            repo=async_structure_repository(cur),
        )
        if row is None:
            return {"status": "already_exists"}
        return row


@router.delete("/api/structure-relations/{relation_id}", response_model=DeletedResponse)
async def delete_relation(relation_id: int) -> Any:
    """Supprime une relation structure. 404 si l'id n'existe pas."""
    async with get_async_cursor() as (cur, conn):
        await structures_service.delete_relation(
            cur, relation_id, repo=async_structure_repository(cur)
        )
        return {"deleted": True}


@router.get("/api/name-forms/{form_id}", response_model=NameFormOut)
async def get_name_form(form_id: int) -> Any:
    """Récupère une forme de nom par son id. 404 si inconnue."""
    async with get_async_cursor() as (cur, _conn):
        row = await get_name_form_async(cur, form_id)
        if not row:
            raise HTTPException(status_code=404, detail="Form not found")
        return row


@router.post("/api/name-forms", response_model=NameFormOut)
async def create_name_form(data: NameFormCreate) -> Any:
    """Crée une forme de nom pour une structure, utilisée par le matching d'adresses.

    `form_text` est normalisé (accents, casse, ponctuation) par le
    service avant insertion. `is_word_boundary` : le match exige
    une frontière de mot dans l'adresse brute. `is_excluding` :
    forme à exclure, pas à matcher (anti-pattern).
    `requires_context_of` : liste d'ids de structures qui doivent
    elles-mêmes matcher l'adresse pour que cette forme active.
    """
    async with get_async_cursor() as (cur, conn):
        return await structures_service.create_name_form(
            cur,
            structure_id=data.structure_id,
            form_text=data.form_text,
            is_word_boundary=data.is_word_boundary,
            is_excluding=data.is_excluding,
            requires_context_of=data.requires_context_of,
            repo=async_structure_repository(cur),
        )


@router.put("/api/name-forms/{form_id}", response_model=NameFormOut)
async def update_name_form(form_id: int, data: NameFormUpdate) -> Any:
    """Met à jour une forme de nom (sélective des champs fournis). 404 si inconnue."""
    fields = data.model_dump(exclude_unset=True)
    async with get_async_cursor() as (cur, conn):
        return await structures_service.update_name_form(
            cur, form_id, fields=fields, repo=async_structure_repository(cur)
        )


@router.delete("/api/name-forms/{form_id}", response_model=DeletedResponse)
async def delete_name_form(form_id: int) -> Any:
    """Supprime une forme de nom. 404 si inconnue."""
    async with get_async_cursor() as (cur, conn):
        await structures_service.delete_name_form(
            cur, form_id, repo=async_structure_repository(cur)
        )
        return {"deleted": True}
