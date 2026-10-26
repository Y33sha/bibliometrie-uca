"""Router du référentiel des entités organisationnelles et de leurs liens. Sert `/api/structures/*`.

Une structure est un laboratoire, une composante, une université, un centre hospitalier, une école ou un site. La table `structure_parents` en exprime le rattachement hiérarchique, qui décide de la clôture d'un périmètre. Les formes de nom, qui servent à reconnaître les structures dans les adresses, s'éditent sous `/name-forms` — celles des personnes, homonymes mais sans rapport, vivent sous `/api/persons`.

Les chemins littéraux se déclarent avant `/{structure_id}` : un segment fixe placé après serait capté par le paramètre.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.repositories.structure_repository import (
    NameFormCreate,
    NameFormUpdate,
    StructureCreate,
    StructureUpdate,
)
from application.services.structures import StructureService
from domain.structures.ror import RorType
from domain.structures.structure import StructureType
from infrastructure.read_models.structures.models import (
    NameFormOut,
    StructureAddressesResponse,
    StructureDashboardResponse,
    StructureDeletionImpact,
    StructureDetailResponse,
    StructureListItem,
    StructureOut,
    StructurePartnersResponse,
)
from infrastructure.read_models.structures.queries import StructuresQueries
from infrastructure.read_models.subjects.models import SubjectFrequency
from interfaces.api.deps import structure_service, structures_queries
from interfaces.api.filters import parse_int_csv, parse_str_csv, parse_vocabulary_csv
from interfaces.api.models import (
    DeletedResponse,
    StructureTutelleCreateResponse,
    TutelleCreate,
)
from interfaces.api.params import TOP_SUBJECTS_LIMIT, SearchTerm, TopSubjectsLimit

router = APIRouter(prefix="/api/structures", tags=["structures"])


@router.get("", response_model=list[StructureListItem])
def list_structures(
    structure_type: str = Query(""),
    search: SearchTerm = "",
    in_perimeter: bool = Query(False),
    queries: StructuresQueries = Depends(structures_queries),
) -> list[StructureListItem]:
    """Liste des structures, filtrable par types, par texte libre et par appartenance au périmètre.

    `structure_type` accepte plusieurs valeurs de l'énumération `structure_type` séparées par des virgules. `search` : matching accent-insensible sur nom / acronyme / code. `in_perimeter` restreint aux structures du périmètre `persons`, clôture comprise : la page publique des laboratoires s'en sert, avec les types que sa configuration lui donne. L'ordre de la liste n'est pas garanti : les consommateurs trient à l'affichage.
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
    structures: StructureService = Depends(structure_service),
) -> StructureOut:
    """Crée une structure. Lève 409 si le `code` ou le `ror_id` est déjà utilisé."""
    return StructureOut.from_structure(structures.create_structure(data))


# ── Tutelles entre structures ────────────────────────────────────


@router.post("/tutelles", response_model=StructureTutelleCreateResponse)
def create_tutelle(
    data: TutelleCreate,
    structures: StructureService = Depends(structure_service),
) -> StructureTutelleCreateResponse:
    """Crée une tutelle parent-enfant entre deux structures.

    Idempotent : une tutelle identique — même parent, même enfant — laisse la table inchangée et rend `{"status": "already_exists"}`. Lève 422 si elle viole l'invariant de graphe : structure liée à elle-même, ou cycle (l'enfant est déjà un ancêtre du parent). Lève 409 si `parent_id` ou `child_id` désigne une structure inexistante.
    """
    row = structures.create_tutelle(parent_id=data.parent_id, child_id=data.child_id)
    if row is None:
        return StructureTutelleCreateResponse.model_validate({"status": "already_exists"})
    return StructureTutelleCreateResponse.model_validate(row)


@router.delete("/tutelles/{tutelle_id}", response_model=DeletedResponse)
def delete_tutelle(
    tutelle_id: int,
    structures: StructureService = Depends(structure_service),
) -> DeletedResponse:
    """Supprime une tutelle. 404 si l'id n'existe pas."""
    structures.delete_tutelle(tutelle_id)
    return DeletedResponse()


# ── Formes de nom ────────────────────────────────────────────────
# Une forme de nom est une écriture sous laquelle une structure se reconnaît dans le texte brut
# d'une adresse. La phase `affiliations` les charge toutes et les apparie ; ces routes les éditent.


@router.post("/name-forms", response_model=NameFormOut)
def create_name_form(
    data: NameFormCreate,
    structures: StructureService = Depends(structure_service),
) -> NameFormOut:
    """Crée une forme de nom pour une structure, utilisée par le matching d'adresses.

    `form_text` est normalisé (accents, casse, ponctuation) par le service avant insertion. `is_word_boundary` : le match exige une frontière de mot dans l'adresse brute. `is_excluding` : forme dont la présence retire la structure des résultats. `requires_context_of` : liste d'ids de structures qui doivent elles-mêmes matcher l'adresse pour que cette forme active. Lève 409 si `structure_id` désigne une structure inexistante.
    """
    return NameFormOut.model_validate(structures.create_name_form(data))


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
    structures: StructureService = Depends(structure_service),
) -> NameFormOut:
    """Met à jour une forme de nom (sélective des champs fournis). 404 si inconnue."""
    return NameFormOut.model_validate(structures.update_name_form(form_id, data))


@router.delete("/name-forms/{form_id}", response_model=DeletedResponse)
def delete_name_form(
    form_id: int,
    structures: StructureService = Depends(structure_service),
) -> DeletedResponse:
    """Supprime une forme de nom. 404 si inconnue."""
    structures.delete_name_form(form_id)
    return DeletedResponse()


# ── Une structure ────────────────────────────────────────────────


@router.get("/{structure_id}", response_model=StructureDetailResponse)
def get_structure(
    structure_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> StructureDetailResponse:
    """Détail complet d'une structure : identifiants + parents + enfants + formes de nom.

    Retourne `{structure, parents, children, forms}`. Les parents sont les structures qui ont cette structure comme `child_id` dans `structure_parents` ; les enfants inversement. 404 si la structure n'existe pas.
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


@router.get("/{structure_id}/partners", response_model=StructurePartnersResponse)
def get_structure_partners(
    structure_id: int,
    year: str = Query(""),
    country: str = Query(""),
    type: str = Query(""),  # noqa: A002 — nom du paramètre de requête
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: StructuresQueries = Depends(structures_queries),
) -> StructurePartnersResponse:
    """Organisations partenaires de la structure, classées par nombre de copublications : les ROR des auteurs de ses publications, ancêtres compris, hors ceux de la structure et de ses tutelles. Filtres par année de publication, pays et type d'organisation ROR, valeurs séparées par des virgules."""
    return queries.get_structure_partners(
        structure_id,
        years=parse_int_csv(year, param="year"),
        countries=[c.lower() for c in parse_str_csv(country)],
        types=parse_vocabulary_csv(type, allowed=tuple(RorType), param="type"),
        page=page,
        per_page=per_page,
    )


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


@router.get("/{structure_id}/deletion-impact", response_model=StructureDeletionImpact)
def get_structure_deletion_impact(
    structure_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> StructureDeletionImpact:
    """Ce que la suppression de la structure emporte, pour la confirmation : formes de nom, tutelles, liens adresse-structure confirmés ou rejetés, périmètres dont elle est une racine. 404 si la structure n'existe pas."""
    impact = queries.get_deletion_impact(structure_id)
    if impact is None:
        raise HTTPException(status_code=404, detail="Structure introuvable")
    return impact


@router.put("/{structure_id}", response_model=StructureOut)
def update_structure(
    structure_id: int,
    data: StructureUpdate,
    structures: StructureService = Depends(structure_service),
) -> StructureOut:
    """Met à jour une structure, champ par champ.

    Seuls les champs présents dans le corps de la requête sont écrits ; `null` efface un champ facultatif. Renvoie 404 sur une structure inconnue.
    """
    return StructureOut.from_structure(structures.update_structure(structure_id, data))


@router.delete("/{structure_id}", response_model=DeletedResponse)
def delete_structure(
    structure_id: int,
    structures: StructureService = Depends(structure_service),
) -> DeletedResponse:
    """Supprime une structure, avec ses formes de nom, ses tutelles et ses liens adresse-structure (`deletion-impact` les compte). 404 si inconnue."""
    structures.delete_structure(structure_id)
    return DeletedResponse()
