"""Router du référentiel des entités organisationnelles et de leurs liens. Sert `/api/structures/*`.

Une structure est un laboratoire, une composante, une université, un centre hospitalier, une école ou un site. La table `structure_relations` en exprime les liens : `est_tutelle_de` pour le rattachement hiérarchique, seul à peser dans la clôture d'un périmètre, et `est_partenaire_de` pour une association sans rattachement. Les formes de nom, qui servent à reconnaître les structures dans les adresses, s'éditent sous `/name-forms` — celles des personnes, homonymes mais sans rapport, vivent sous `/api/persons`.

Les chemins littéraux se déclarent avant `/{structure_id}` : un segment fixe placé après serait capté par le paramètre.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.structures_queries import (
    NameFormOut,
    StructureAddressesResponse,
    StructureDashboardResponse,
    StructureDetailResponse,
    StructureListItem,
    StructureOut,
    StructuresQueries,
)
from application.ports.api.subjects_queries import SubjectFrequency
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.structure_repository import StructureRepository
from application.services.structures import commands as structure_commands
from domain.structures.structure import StructureType
from interfaces.api.deps import (
    audit_repo,
    db_conn,
    perimeter_repo,
    structure_repo,
    structures_queries,
)
from interfaces.api.filters import parse_vocabulary_csv
from interfaces.api.models import (
    DeletedResponse,
    NameFormCreate,
    NameFormUpdate,
    RelationCreate,
    StructureCreate,
    StructureRelationCreateResponse,
    StructureUpdate,
)
from interfaces.api.params import TOP_SUBJECTS_LIMIT, TopSubjectsLimit

router = APIRouter(prefix="/api/structures", tags=["structures"])


@router.get("", response_model=list[StructureListItem])
def list_structures(
    structure_type: str = Query(""),
    search: str = Query(""),
    in_perimeter: bool = Query(False),
    queries: StructuresQueries = Depends(structures_queries),
) -> list[StructureListItem]:
    """Liste des structures, filtrable par types, par texte libre et par appartenance au périmètre.

    `structure_type` accepte plusieurs valeurs de l'énumération `structure_type` séparées par des virgules. `search` : matching accent-insensible sur nom / acronyme / code. `in_perimeter` restreint aux structures du périmètre `persons`, clôture comprise : la page publique des laboratoires s'en sert, avec les types que sa configuration lui donne. Tri canonique par type (labo > universite > onr > chu > ecole > site > autre) puis nom.
    """
    return queries.list_structures(
        types=parse_vocabulary_csv(
            structure_type, allowed=tuple(StructureType), param="structure_type"
        ),
        search=search,
        in_perimeter=in_perimeter,
    )


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
    perimeters: PerimeterRepository = Depends(perimeter_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> StructureRelationCreateResponse:
    """Crée une relation parent-enfant entre deux structures.

    Idempotent : une relation identique — même parent, même enfant, même type — laisse la table inchangée et rend `{"status": "already_exists"}`. Lève 400 si la relation viole l'invariant de graphe : structure liée à elle-même, ou cycle (l'enfant est déjà un ancêtre du parent). Lève 409 si `parent_id` ou `child_id` désigne une structure inexistante.
    """
    row = structure_commands.create_relation(
        conn,
        parent_id=data.parent_id,
        child_id=data.child_id,
        relation_type=data.relation_type,
        repo=repo,
        perimeter_repo=perimeters,
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
    perimeters: PerimeterRepository = Depends(perimeter_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> DeletedResponse:
    """Supprime une relation structure. 404 si l'id n'existe pas."""
    structure_commands.delete_relation(
        conn, relation_id, repo=repo, perimeter_repo=perimeters, audit_repo=audit
    )
    return DeletedResponse()


# ── Formes de nom ────────────────────────────────────────────────
# Une forme de nom est une écriture sous laquelle une structure se reconnaît dans le texte brut
# d'une adresse. La phase `affiliations` les charge toutes et les apparie ; ces routes les éditent.


@router.post("/name-forms", response_model=NameFormOut)
def create_name_form(
    data: NameFormCreate,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> NameFormOut:
    """Crée une forme de nom pour une structure, utilisée par le matching d'adresses.

    `form_text` est normalisé (accents, casse, ponctuation) par le service avant insertion. `is_word_boundary` : le match exige une frontière de mot dans l'adresse brute. `is_excluding` : forme dont la présence retire la structure des résultats. `requires_context_of` : liste d'ids de structures qui doivent elles-mêmes matcher l'adresse pour que cette forme active. Lève 409 si `structure_id` désigne une structure inexistante.
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


@router.get("/name-forms/{form_id}", response_model=NameFormOut)
def get_name_form(
    form_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> NameFormOut:
    """Récupère une forme de nom par son id. 404 si inconnue."""
    row = queries.get_name_form(form_id)
    if not row:
        raise HTTPException(status_code=404, detail="Forme de nom introuvable")
    return row


@router.put("/name-forms/{form_id}", response_model=NameFormOut)
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


@router.delete("/name-forms/{form_id}", response_model=DeletedResponse)
def delete_name_form(
    form_id: int,
    conn: Connection = Depends(db_conn),
    repo: StructureRepository = Depends(structure_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> DeletedResponse:
    """Supprime une forme de nom. 404 si inconnue."""
    structure_commands.delete_name_form(conn, form_id, repo=repo, audit_repo=audit)
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


@router.get("/{structure_id}/addresses", response_model=StructureAddressesResponse)
def get_structure_addresses(
    structure_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: StructuresQueries = Depends(structures_queries),
) -> StructureAddressesResponse:
    """Adresses rattachées à la structure, le rattachement rejeté écarté."""
    return queries.get_structure_addresses(structure_id, page=page, per_page=per_page)


@router.get("/{structure_id}/dashboard", response_model=StructureDashboardResponse)
def get_structure_dashboard(
    structure_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> StructureDashboardResponse:
    """Agrégats de la structure : publications par année, accès ouvert, collaborations internationales."""
    return queries.get_structure_dashboard(structure_id)


@router.get("/{structure_id}/subjects", response_model=list[SubjectFrequency])
def get_structure_subjects(
    structure_id: int,
    limit: TopSubjectsLimit = TOP_SUBJECTS_LIMIT,
    queries: StructuresQueries = Depends(structures_queries),
) -> list[SubjectFrequency]:
    """Sujets les plus fréquents des publications de la structure (nuage de mots)."""
    return queries.get_structure_subjects(structure_id, limit=limit)


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
    perimeters: PerimeterRepository = Depends(perimeter_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> DeletedResponse:
    """Supprime une structure. Cascade sur les relations et formes de noms liées. 404 si inconnue."""
    structure_commands.delete_structure(
        conn, structure_id, repo=repo, perimeter_repo=perimeters, audit_repo=audit
    )
    return DeletedResponse()
