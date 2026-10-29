"""Router du référentiel des entités organisationnelles et de leurs liens. Sert `/api/structures/*`.

Une structure est un laboratoire, une composante, une université, un centre hospitalier, une école ou un site. La table `structure_parents` décrit leurs tutelles, qui décident des structures d'un périmètre. Les formes de nom, qui servent à reconnaître les structures dans les adresses, s'éditent sous `/name-forms` ; celles des personnes, sans rapport, vivent sous `/api/persons`.

Les chemins littéraux se déclarent avant `/{structure_id}` : un segment fixe placé après serait capté par le paramètre.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

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
    StructureDeletionImpact,
    StructureDetailResponse,
    StructureFilters,
    StructureListItem,
    StructureListResponse,
    StructureOut,
    StructurePartnersResponse,
    StructuresFacetsResponse,
    StructureSort,
)
from infrastructure.read_models.structures.queries import StructuresQueries
from infrastructure.read_models.subjects.models import SubjectFrequency
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import structure_service, structures_queries
from interfaces.api.filters import (
    parse_ids_with_none,
    parse_int_csv,
    parse_str_csv,
    parse_vocabulary_csv,
)
from interfaces.api.models import (
    DeletedResponse,
    StructureTutelleCreateResponse,
    TutelleCreate,
)
from interfaces.api.params import TOP_SUBJECTS_LIMIT, SearchTerm, TopSubjectsLimit
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/structures", tags=["structures"])


def structure_filters(
    search: SearchTerm = "",
    structure_type: str = Query(""),
    tutelle_id: str = Query(""),
    perimeter_id: str = Query(""),
) -> StructureFilters:
    """Filtres communs à la liste des structures, à ses facettes et à son export.

    Les valeurs multiples se séparent par des virgules. `search` cherche dans le nom, l'acronyme et le code, sans tenir compte des accents. `perimeter_id` accepte la sentinelle `none`, qui retient les structures hors de tout périmètre.
    """
    perimeter_ids, perimeter_none = parse_ids_with_none(perimeter_id, param="perimeter_id")
    return StructureFilters(
        search=search,
        types=parse_vocabulary_csv(
            structure_type, allowed=tuple(StructureType), param="structure_type"
        ),
        tutelle_ids=parse_int_csv(tutelle_id, param="tutelle_id"),
        perimeter_ids=perimeter_ids,
        perimeter_none=perimeter_none,
    )


Filters = Annotated[StructureFilters, Depends(structure_filters)]


@router.get("", response_model=StructureListResponse)
def list_structures(
    filters: Filters,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: StructureSort = "acronym_asc",
    queries: StructuresQueries = Depends(structures_queries),
) -> StructureListResponse:
    """Liste paginée des structures."""
    return queries.list_structures(filters=filters, sort=sort, page=page, per_page=per_page)


@router.get("/all", response_model=list[StructureListItem])
def list_all_structures(
    queries: StructuresQueries = Depends(structures_queries),
) -> list[StructureListItem]:
    """Toutes les structures, triées par nom, pour les sélecteurs de structure."""
    return queries.list_all_structures()


@router.get("/facets", response_model=StructuresFacetsResponse)
def structures_facets(
    filters: Filters,
    queries: StructuresQueries = Depends(structures_queries),
) -> StructuresFacetsResponse:
    """Décomptes par option des facettes de la liste des structures.

    Chaque facette écarte sa propre dimension de la clause WHERE.
    """
    return queries.structures_facets(filters=filters)


@router.get("/export.csv")
def export_structures_csv(
    filters: Filters,
    sort: StructureSort = "acronym_asc",
    queries: StructuresQueries = Depends(structures_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV de la liste des structures, aux filtres et au tri de la liste."""
    return csv_response(
        queries.export_structures_csv(filters=filters, sort=sort),
        filename="structures.csv",
        slot=slot,
    )


@router.post("", response_model=StructureOut)
def create_structure(
    data: StructureCreate,
    structures: StructureService = Depends(structure_service),
) -> StructureOut:
    """Crée une structure. Renvoie 409 si le `code` ou le `ror_id` est déjà utilisé."""
    return StructureOut.from_structure(structures.create_structure(data))


# ── Tutelles entre structures ────────────────────────────────────


@router.post("/tutelles", response_model=StructureTutelleCreateResponse)
def create_tutelle(
    data: TutelleCreate,
    structures: StructureService = Depends(structure_service),
) -> StructureTutelleCreateResponse:
    """Crée une tutelle entre deux structures.

    Une tutelle existante (même parent, même enfant) laisse la table inchangée et renvoie `{"status": "already_exists"}`. Renvoie 422 si la tutelle viole le graphe : structure liée à elle-même, ou cycle (l'enfant est déjà un ancêtre du parent). Renvoie 409 si `parent_id` ou `child_id` désigne une structure inexistante.
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
    """Supprime une tutelle. Renvoie 404 si elle n'existe pas."""
    structures.delete_tutelle(tutelle_id)
    return DeletedResponse()


# ── Formes de nom ────────────────────────────────────────────────
# Une forme de nom est une écriture sous laquelle une structure se reconnaît dans le texte brut d'une adresse. La phase `affiliations` les charge toutes et les apparie ; ces routes les éditent.


@router.post("/name-forms", response_model=NameFormOut)
def create_name_form(
    data: NameFormCreate,
    structures: StructureService = Depends(structure_service),
) -> NameFormOut:
    """Crée une forme de nom pour une structure, qui sert à la reconnaître dans les adresses.

    Le service normalise `form_text` (accents, casse, ponctuation) avant l'insertion. `is_word_boundary` : la forme doit former un mot entier dans l'adresse. `is_excluding` : la présence de la forme retire la structure du résultat. `requires_context_of` : structures dont l'une doit aussi être reconnue dans l'adresse pour que la forme vaille. Renvoie 409 si `structure_id` désigne une structure inexistante.
    """
    return NameFormOut.model_validate(structures.create_name_form(data))


@router.get("/name-forms/{form_id}", response_model=NameFormOut)
def get_name_form(
    form_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> NameFormOut:
    """Forme de nom, par son identifiant. Renvoie 404 si elle est inconnue."""
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
    """Met à jour les champs fournis d'une forme de nom. Renvoie 404 si elle est inconnue."""
    return NameFormOut.model_validate(structures.update_name_form(form_id, data))


@router.delete("/name-forms/{form_id}", response_model=DeletedResponse)
def delete_name_form(
    form_id: int,
    structures: StructureService = Depends(structure_service),
) -> DeletedResponse:
    """Supprime une forme de nom. Renvoie 404 si elle est inconnue."""
    structures.delete_name_form(form_id)
    return DeletedResponse()


# ── Une structure ────────────────────────────────────────────────


@router.get("/{structure_id}", response_model=StructureDetailResponse)
def get_structure(
    structure_id: int,
    queries: StructuresQueries = Depends(structures_queries),
) -> StructureDetailResponse:
    """Détail complet d'une structure : `{structure, parents, children, forms}`, soit la structure, ses tutelles, ses sous-structures et ses formes de nom. Renvoie 404 si la structure n'existe pas."""
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
    """Ce que la suppression de la structure emporte, pour la confirmation : formes de nom, tutelles, liens adresse-structure confirmés ou rejetés, périmètres dont elle est une racine. Renvoie 404 si la structure n'existe pas."""
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
    """Supprime une structure, avec ses formes de nom, ses tutelles et ses liens adresse-structure (`deletion-impact` les compte). Renvoie 404 si elle est inconnue."""
    structures.delete_structure(structure_id)
    return DeletedResponse()
