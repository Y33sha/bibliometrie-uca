"""Router des revues : listes, recherche, édition, fusion. Sert `/api/serials/*`.

Les chemins littéraux — `/oa-models`, `/types`, `/facets`, `/export.csv` — précèdent `/{serial_id}`, qui les accepterait sinon comme identifiant.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from application.ports.repositories.serial_repository import SerialUpdate
from application.services.serials import SerialService
from domain.merge import MergedEntity
from domain.serials.serial import (
    OA_MODEL_LABELS_FR,
    OA_MODELS,
    SERIAL_TYPE_LABELS_FR,
    SERIAL_TYPES,
)
from infrastructure.read_models._common import EntityFacetResponse
from infrastructure.read_models.serials.models import (
    DoiNamespaceConflictsResponse,
    LikelyProceedingsResponse,
    SerialDetailResponse,
    SerialDuplicatesResponse,
    SerialFilters,
    SerialListResponse,
    SerialsFacetsResponse,
    SerialSort,
)
from infrastructure.read_models.serials.queries import SerialQueries
from infrastructure.read_models.subjects.models import SubjectFrequency
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import entity_detail, serial_queries, serial_service
from interfaces.api.entity_detail import EntityDetail
from interfaces.api.filters import parse_vocabulary_csv
from interfaces.api.models import (
    EnumOption,
    MergeRequest,
    MergeResponse,
    OkResponse,
    SerialTypeChange,
    SerialTypeChangeImpact,
    TotalCountResponse,
)
from interfaces.api.params import TOP_SUBJECTS_LIMIT, SearchTerm, TopSubjectsLimit
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/serials", tags=["serials"])


@router.get("/oa-models", response_model=list[EnumOption])
def list_oa_models() -> list[EnumOption]:
    """Valeurs possibles de `oa_model` avec leur libellé français.

    La source de vérité côté Python est `domain.serials.journal.OA_MODELS` et `OA_MODEL_LABELS_FR`. Alimente la facette « Modèle OA » des listes de revues et la liste déroulante de la modale d'édition admin.
    """
    return [EnumOption(value=v, label_fr=OA_MODEL_LABELS_FR[v]) for v in OA_MODELS]


@router.get("/types", response_model=list[EnumOption])
def list_serial_types() -> list[EnumOption]:
    """Valeurs possibles de l'enum `serial_type` avec leur libellé français.

    La source de vérité côté Python est `domain.serials.journal.SERIAL_TYPES` et `SERIAL_TYPE_LABELS_FR`, dont un test d'intégration vérifie l'accord avec l'enum SQL. Alimente la liste déroulante de la page admin des revues et la colonne « Type » des pages publiques.
    """
    return [EnumOption(value=v, label_fr=SERIAL_TYPE_LABELS_FR[v]) for v in SERIAL_TYPES]


def serial_filters(
    search: SearchTerm = "",
    publisher_id: int | None = Query(None),
    serial_type: str = Query(""),
    is_in_doaj: bool | None = Query(None),
    oa_model: str = Query(""),
    has_publications: bool | None = Query(None),
) -> SerialFilters:
    """Filtres communs à la liste des revues et à ses facettes.

    `serial_type` et `oa_model` acceptent plusieurs valeurs séparées par des virgules, prises dans les énumérations du domaine ; une valeur inconnue rend 422. `search` porte sur le titre et sur les ISSN de la revue, et est ignoré en deçà de deux caractères.
    """
    return SerialFilters(
        search=search,
        publisher_id=publisher_id,
        serial_types=parse_vocabulary_csv(serial_type, allowed=SERIAL_TYPES, param="serial_type"),
        is_in_doaj=is_in_doaj,
        oa_models=parse_vocabulary_csv(oa_model, allowed=OA_MODELS, param="oa_model"),
        has_publications=has_publications,
    )


@router.get("/facets", response_model=SerialsFacetsResponse)
def serials_facets(
    filters: SerialFilters = Depends(serial_filters),
    queries: SerialQueries = Depends(serial_queries),
) -> SerialsFacetsResponse:
    """Comptes par option des facettes de la liste des revues.

    Convention partagée avec `/api/publications/facets` : chaque facette écarte sa propre dimension de la clause WHERE, de sorte que son décompte annonce le nombre de revues atteignables si l'option était cochée ou décochée.
    """
    return queries.serials_facets(filters=filters)


@router.get("/facets/entities", response_model=EntityFacetResponse)
def serials_entity_facet(
    kind: Literal["publisher"] = Query(...),
    entity_search: SearchTerm = "",
    filters: SerialFilters = Depends(serial_filters),
    queries: SerialQueries = Depends(serial_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs : les premiers éditeurs sous les filtres actifs, avec leur nombre de revues.

    Les éditeurs sont trop nombreux pour être tous proposés, d'où une facette bornée et une recherche par nom. `entity_search` cherche dans les noms d'éditeur, là où `search` filtre les revues sur leur titre et leurs ISSN.

    `kind` n'admet que `publisher` : il tient au contrat de la facette d'entité, partagé avec les listes de publications et les tableaux de bord.
    """
    return queries.serials_publisher_facet(search=entity_search, filters=filters)


@router.get("", response_model=SerialListResponse)
def list_serials(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: SerialSort = "title_asc",
    filters: SerialFilters = Depends(serial_filters),
    queries: SerialQueries = Depends(serial_queries),
) -> SerialListResponse:
    """Liste paginée des revues, avec le décompte de leurs publications.

    `has_publications` retient les revues qui ont au moins une publication (`true`) ou aucune (`false`). `sort` accepte `title`, `publisher` et `publications`, suffixés de `_asc` ou `_desc` ; toute autre valeur rend un 422.
    """
    return queries.list_serials(filters=filters, sort=sort, page=page, per_page=per_page)


@router.get("/export.csv")
def export_serials_csv(
    sort: SerialSort = "title_asc",
    filters: SerialFilters = Depends(serial_filters),
    queries: SerialQueries = Depends(serial_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV de la liste des revues, aux filtres et au tri de la liste."""
    return csv_response(
        queries.export_serials_csv(filters=filters, sort=sort),
        filename="publications-en-serie.csv",
        slot=slot,
    )


# ── Files de triage ──────────────────────────────────────────────


@router.get("/same-titles/count", response_model=TotalCountResponse)
def serials_with_same_title_count(
    queries: SerialQueries = Depends(serial_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Titres identiques » (badge)."""
    return TotalCountResponse(total=len(queries.serials_with_same_title().groups))


@router.get("/same-titles", response_model=SerialDuplicatesResponse)
def serials_with_same_title(
    queries: SerialQueries = Depends(serial_queries),
) -> SerialDuplicatesResponse:
    """Groupes de revues de même titre normalisé, à fusionner à la main.

    Deux revues de même titre qui ont chacune un ISSN sont des homonymes probables : elles sont écartées.
    """
    return queries.serials_with_same_title()


@router.get("/shared-issns/count", response_model=TotalCountResponse)
def serials_sharing_issn_count(
    queries: SerialQueries = Depends(serial_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « ISSN partagés » (badge)."""
    return TotalCountResponse(total=len(queries.serials_sharing_issn().groups))


@router.get("/shared-issns", response_model=SerialDuplicatesResponse)
def serials_sharing_issn(
    queries: SerialQueries = Depends(serial_queries),
) -> SerialDuplicatesResponse:
    """Groupes de revues où le même ISSN est actif, à fusionner à la main."""
    return queries.serials_sharing_issn()


@router.get("/likely-proceedings/count", response_model=TotalCountResponse)
def likely_proceedings_count(
    queries: SerialQueries = Depends(serial_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Recueils d'actes probables » (badge)."""
    return TotalCountResponse(total=len(queries.likely_proceedings().serials))


@router.get("/likely-proceedings", response_model=LikelyProceedingsResponse)
def likely_proceedings(
    queries: SerialQueries = Depends(serial_queries),
) -> LikelyProceedingsResponse:
    """Revues typées `journal` dont la majorité des documents sont des articles de congrès, à typer à la main."""
    return queries.likely_proceedings()


@router.get("/doi-namespace-conflicts/count", response_model=TotalCountResponse)
def doi_namespace_conflicts_count(
    queries: SerialQueries = Depends(serial_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Contredites par le DOI » (badge)."""
    return TotalCountResponse(total=len(queries.doi_namespace_conflicts().conflicts))


@router.get("/doi-namespace-conflicts", response_model=DoiNamespaceConflictsResponse)
def doi_namespace_conflicts(
    queries: SerialQueries = Depends(serial_queries),
) -> DoiNamespaceConflictsResponse:
    """Paires de revues dont l'une porte des enregistrements dont le DOI tombe dans l'espace de noms de l'autre."""
    return queries.doi_namespace_conflicts()


@router.get("/{serial_id}", response_model=SerialDetailResponse)
def get_serial(
    serial_id: int,
    queries: SerialQueries = Depends(serial_queries),
    detail: EntityDetail = Depends(entity_detail(MergedEntity.SERIAL)),
) -> SerialDetailResponse:
    """Profil complet d'une revue, pour sa page publique.

    Porte ses métadonnées, la réponse DOAJ brute et sa date d'import, et le décompte de ses publications.
    """
    return detail.found(queries.get_serial_detail(serial_id))


@router.get("/{serial_id}/subjects", response_model=list[SubjectFrequency])
def get_serial_subjects(
    serial_id: int,
    limit: TopSubjectsLimit = TOP_SUBJECTS_LIMIT,
    queries: SerialQueries = Depends(serial_queries),
) -> list[SubjectFrequency]:
    """Sujets les plus fréquents des publications de la revue, pour l'onglet tableau de bord.

    Les sujets trop génériques sont écartés : ils noieraient les autres. Une revue sans publication indexée donne une liste vide.
    """
    return queries.get_serial_subjects(serial_id, limit=limit)


@router.post(
    "/{serial_id}/type-change-impact",
    response_model=SerialTypeChangeImpact,
)
def get_type_change_impact(
    serial_id: int,
    body: SerialTypeChange,
    serials: SerialService = Depends(serial_service),
) -> SerialTypeChangeImpact:
    """Compte les publications de la revue dont le `doc_type` changerait si son `serial_type` passait à la valeur demandée.

    L'aperçu applique réellement le changement — écriture du type, recalcul des corrections sur les publications sources, rafraîchissement — dans un `SAVEPOINT` annulé ensuite. Il emprunte donc le chemin exact de l'édition, et aucune écriture ne survit. Renvoie 404 sur une revue inconnue, comme l'édition qu'il simule.

    La méthode est POST bien qu'aucune écriture ne survive : l'aperçu écrit, pose les verrous de l'édition et en coûte le prix. Un GET s'annonce sans effet, et la garde d'authentification, qui s'applique aux méthodes d'écriture, laisserait passer une action admin.
    """
    count = serials.preview_type_change_impact(serial_id, body.serial_type)
    return SerialTypeChangeImpact(count=count)


@router.put("/{serial_id}", response_model=OkResponse)
def update_serial(
    serial_id: int,
    body: SerialUpdate,
    serials: SerialService = Depends(serial_service),
) -> OkResponse:
    """Met à jour une revue, champ par champ.

    Seuls les champs présents dans le corps de la requête sont écrits (`exclude_unset=True`). Renvoie 404 sur une revue inconnue.

    Un `serial_type` qui change de valeur entraîne la requalification du `doc_type` des publications rattachées, dans la même transaction (`requalify_publications_for_serial`). L'endpoint `type-change-impact` en donne l'ampleur avant confirmation.
    """
    serials.update_serial(serial_id, body)
    return OkResponse()


@router.post("/{serial_id}/merge", response_model=MergeResponse)
def merge(
    serial_id: int,
    body: MergeRequest,
    serials: SerialService = Depends(serial_service),
) -> MergeResponse:
    """Fusionne la revue `source_id` dans la revue `serial_id`.

    Les publications et les métadonnées de la source passent à la cible, puis la source est supprimée. Les publications absorbées sont requalifiées contre le `serial_type` de la cible (`merge_serials`). Renvoie 422 sur deux identifiants égaux, 404 si l'une des deux revues est introuvable.
    """
    serials.merge_serials(serial_id, body.source_id)
    return MergeResponse(merged=True, source_id=body.source_id, target_id=serial_id)
