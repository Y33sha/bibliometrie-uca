"""Router des personnes : annuaire, profil, files de triage et décisions de l'administration. Sert `/api/persons/*`.

Les lectures passent par `PersonsQueries`, les écritures par le service `PersonService`. Les décisions qui concernent les contributions vivent dans `contributions.py`.

Les chemins littéraux (`/search`, `/export.csv`, `/facets`, files de triage, registre des identifiants) précèdent tous `/{person_id}`, qui accepterait sinon n'importe lequel comme identifiant.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from application.services.persons import PersonService
from domain.merge import MergedEntity
from domain.persons.identifier_attribution import AttributionOutcome
from domain.persons.person import PersonExclusion
from infrastructure.read_models.persons.models import (
    AmbiguousNameFormsResponse,
    DistinctPersonOut,
    IdentifierConflictsResponse,
    NameDuplicatesResponse,
    NameFormContributionsResponse,
    NameFormSummaryOut,
    PersonAddressesResponse,
    PersonFilters,
    PersonListResponse,
    PersonOut,
    PersonProfileResponse,
    PersonSearchResult,
    PersonsFacetsResponse,
    PersonSort,
    PersonThesesResponse,
    SharingPersonOut,
)
from infrastructure.read_models.persons.queries import PersonsQueries
from infrastructure.read_models.subjects.models import SubjectFrequency
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import entity_detail, person_service, persons_queries
from interfaces.api.entity_detail import EntityDetail
from interfaces.api.filters import parse_str_csv, parse_vocabulary_csv
from interfaces.api.models import (
    AddIdentifier,
    AddIdentifierResponse,
    DetachContributions,
    DetachContributionsResponse,
    IdentifierStatusResponse,
    MarkDistinctPersons,
    MergeRequest,
    MergeResponse,
    NameFormStatusResponse,
    OkResponse,
    SetPersonExclusion,
    TotalCountResponse,
    UpdateIdentifierStatus,
    UpdateNameFormStatus,
    UpdatePersonName,
)
from interfaces.api.params import (
    MAX_SEARCH_LENGTH,
    TOP_SUBJECTS_LIMIT,
    SearchTerm,
    TextParam,
    TopSubjectsLimit,
)
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/persons", tags=["persons"])


# ── Listes et facettes ───────────────────────────────────────────

# Valeur du filtre `exclusion` qui désigne les personnes retenues.
RETAINED = "none"


def person_filters(
    search: SearchTerm = "",
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: bool | None = Query(None),
    has_idhal: bool | None = Query(None),
    has_idref: bool | None = Query(None),
    has_rh: bool | None = Query(None),
    has_pending_forms: bool | None = Query(None),
    has_pending_identifiers: bool | None = Query(None),
    exclusion: str = Query(""),
    active: bool | None = Query(None),
    lab_id: int | None = Query(None),
) -> PersonFilters:
    """Filtres communs à la liste des personnes et à ses facettes.

    `department`, `role` et `exclusion` acceptent plusieurs valeurs séparées par des virgules. `exclusion` prend des motifs d'exclusion et `none` pour les personnes retenues ; omis, il laisse tout passer, et l'annuaire public pose `exclusion=none`. `active=true` retient les personnes qui ont une contribution ou une fiche RH ; l'annuaire public le pose aussi. `lab_id` restreint aux personnes d'un laboratoire et y restreint leurs dénombrements.
    """
    return PersonFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        has_pending_forms=has_pending_forms,
        has_pending_identifiers=has_pending_identifiers,
        exclusions=[
            None if v == RETAINED else PersonExclusion(v)
            for v in parse_vocabulary_csv(
                exclusion,
                allowed={RETAINED, *(e.value for e in PersonExclusion)},
                param="exclusion",
            )
        ],
        active=active,
        lab_id=lab_id,
    )


@router.get("/search", response_model=list[PersonSearchResult])
def search_persons(
    search: str = Query("", min_length=2, max_length=MAX_SEARCH_LENGTH),
    limit: int = Query(10, ge=1, le=30),
    queries: PersonsQueries = Depends(persons_queries),
) -> list[PersonSearchResult]:
    """Recherche rapide de personnes (autocomplétion)."""
    return queries.search_persons(search=search, limit=limit)


@router.get("", response_model=PersonListResponse)
def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: PersonSort = Query("name_asc"),
    filters: PersonFilters = Depends(person_filters),
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonListResponse:
    """Liste paginée des personnes.

    L'annuaire public et la liste de l'administration appellent tous deux cette lecture, avec des filtres différents.
    """
    return queries.list_persons(filters=filters, page=page, per_page=per_page, sort=sort)


@router.get("/export.csv")
def export_persons_csv(
    sort: PersonSort = Query("name_asc"),
    filters: PersonFilters = Depends(person_filters),
    queries: PersonsQueries = Depends(persons_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV de la liste des personnes, aux filtres et au tri de la liste."""
    return csv_response(
        queries.export_persons_csv(filters=filters, sort=sort),
        filename="chercheurs.csv",
        slot=slot,
    )


@router.get("/facets", response_model=PersonsFacetsResponse)
def persons_facets(
    filters: PersonFilters = Depends(person_filters),
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonsFacetsResponse:
    """Facettes dynamiques de la liste des personnes : chaque facette décompte sous les autres filtres."""
    return queries.persons_facets(filters=filters)


# ── Files de triage ──────────────────────────────────────────────


@router.get("/ambiguous-name-forms/count", response_model=TotalCountResponse)
def ambiguous_name_forms_count(
    queries: PersonsQueries = Depends(persons_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Formes ambiguës » (badge)."""
    return TotalCountResponse(total=queries.ambiguous_name_forms_count())


@router.get("/ambiguous-name-forms", response_model=AmbiguousNameFormsResponse)
def ambiguous_name_forms(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries),
) -> AmbiguousNameFormsResponse:
    """Formes de nom d'au moins deux personnes, dont au moins un lien en attente, paginées."""
    return queries.ambiguous_name_forms(page=page, per_page=per_page)


@router.get("/identifier-conflicts/count", response_model=TotalCountResponse)
def identifier_conflicts_count(
    queries: PersonsQueries = Depends(persons_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Conflits d'identifiant » (badge)."""
    return TotalCountResponse(total=queries.identifier_conflicts_count())


@router.get("/identifier-conflicts", response_model=IdentifierConflictsResponse)
def identifier_conflicts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries),
) -> IdentifierConflictsResponse:
    """Paires de personnes partageant un identifiant brut (ORCID, IdRef, hal_person_id ou idHAL), paginées.

    Ce sont des doublons probables ou des erreurs d'attribution, que l'administration tranche.
    """
    return queries.identifier_conflicts(page=page, per_page=per_page)


@router.get("/name-duplicates/count", response_model=TotalCountResponse)
def name_duplicates_count(
    queries: PersonsQueries = Depends(persons_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Doublons par nom » (badge)."""
    return TotalCountResponse(total=queries.name_duplicates_count())


@router.get("/name-duplicates", response_model=NameDuplicatesResponse)
def name_duplicates(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries),
) -> NameDuplicatesResponse:
    """Paires de personnes aux noms compatibles, paginées, triées par force de réseau : co-auteurs, publications co-signées, laboratoires et revues en commun.

    Les doublons probables viennent en tête, les homonymes en fin.
    """
    return queries.name_duplicates(page=page, per_page=per_page)


@router.post("/mark-distinct", response_model=OkResponse)
def mark_persons_distinct(
    body: MarkDistinctPersons,
    persons: PersonService = Depends(person_service),
) -> OkResponse:
    """Marque deux personnes comme distinctes : les files de triage par nom et par identifiant écartent la paire.

    Renvoie 422 sur deux identifiants égaux (`mark_distinct`).
    """
    persons.mark_distinct(body.person_id_a, body.person_id_b)
    return OkResponse()


# ── Registre des identifiants ────────────────────────────────────


@router.patch("/identifiers/{ident_id}/status", response_model=IdentifierStatusResponse)
def update_identifier_status(
    ident_id: int,
    body: UpdateIdentifierStatus,
    persons: PersonService = Depends(person_service),
) -> IdentifierStatusResponse:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected). Une confirmation ou un rejet s'étend aux identifiants `pending` de la même personne que contiennent les mêmes comptes HAL ; `propagated` les compte. Un rejet marque pour la redécision de leur personne les contributions que ses identifiants rejetés lui rattachent : le run suivant les redécide.

    Renvoie 404 sur un identifiant introuvable (`update_identifier_status`).
    """
    result = persons.update_identifier_status(ident_id, body.status)
    return IdentifierStatusResponse(
        id=result.id, status=result.status, propagated=result.propagated
    )


# ── Une personne : lectures ──────────────────────────────────────


@router.get("/{person_id}", response_model=PersonProfileResponse)
def person_profile(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
    detail: EntityDetail = Depends(entity_detail(MergedEntity.PERSON)),
) -> PersonProfileResponse:
    """Profil public complet d'une personne."""
    return detail.found(queries.person_profile(person_id))


@router.get("/{person_id}/curation", response_model=PersonOut)
def person_curation(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonOut:
    """Une personne sous la projection de la liste de l'administration : drapeau de rejet, identifiants avec leur statut et leur source, formes de nom avec leur état d'arbitrage.

    Alimente le panneau latéral ouvert directement par son URL, hors de la liste qui contient d'ordinaire ces données.
    """
    person = queries.person_curation(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Personne introuvable")
    return person


@router.get("/{person_id}/theses", response_model=PersonThesesResponse)
def person_theses(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonThesesResponse:
    """Thèses liées à cette personne par un rôle autre qu'auteur."""
    return queries.person_theses(person_id)


@router.get("/{person_id}/addresses", response_model=PersonAddressesResponse)
def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonAddressesResponse:
    """Adresses distinctes utilisées dans les contributions sources de cette personne."""
    return queries.person_addresses(person_id, page=page, per_page=per_page)


@router.get("/{person_id}/subjects", response_model=list[SubjectFrequency])
def person_subjects(
    person_id: int,
    limit: TopSubjectsLimit = TOP_SUBJECTS_LIMIT,
    queries: PersonsQueries = Depends(persons_queries),
) -> list[SubjectFrequency]:
    """Sujets les plus fréquents des publications de cette personne (nuage de mots)."""
    return queries.person_subjects(person_id, limit=limit)


@router.get("/{person_id}/sharing-name-forms", response_model=list[SharingPersonOut])
def persons_sharing_name_form(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> list[SharingPersonOut]:
    """Personnes qui partagent au moins une forme de nom avec celle-ci, candidates à l'absorption."""
    return queries.persons_sharing_name_form(person_id)


@router.get("/{person_id}/distinct-persons", response_model=list[DistinctPersonOut])
def distinct_persons(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> list[DistinctPersonOut]:
    """Personnes déclarées distinctes de celle-ci."""
    return queries.distinct_persons(person_id)


@router.get("/{person_id}/name-forms", response_model=list[NameFormSummaryOut])
def person_name_forms(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> list[NameFormSummaryOut]:
    """Formes de nom de la personne, avec leur état d'arbitrage.

    Servies à part de la liste : seule la fiche d'une personne les affiche, et les inclure dans chaque ligne pèserait les deux tiers de la réponse.
    """
    return queries.person_name_forms(person_id)


@router.get("/{person_id}/name-form-contributions", response_model=NameFormContributionsResponse)
def name_form_contributions(
    person_id: int,
    name_form: TextParam = Query(...),
    queries: PersonsQueries = Depends(persons_queries),
) -> NameFormContributionsResponse:
    """Contributions sources d'une forme de nom, et autres personnes qui la partagent."""
    return queries.name_form_contributions(person_id, name_form)


# ── Une personne : identifiants ──────────────────────────────────


@router.post("/{person_id}/identifiers", response_model=AddIdentifierResponse)
def add_person_identifier(
    person_id: int,
    data: AddIdentifier,
    queries: PersonsQueries = Depends(persons_queries),
    persons: PersonService = Depends(person_service),
) -> AddIdentifierResponse:
    """Ajoute à la main un identifiant (ORCID, idHAL ou IdRef) à une personne.

    La décision (insertion, idempotence, réattribution, conflit) appartient à `add_identifier`, dont l'origine par défaut est manuelle (`IdentifierOrigin.MANUAL`) : il refuse alors les types qu'aucun humain n'attribue, et vérifie l'existence de la personne. Le router traduit l'issue en réponse. Les handlers globaux traduisent la personne absente (`NotFoundError`) en 404, le conflit (`IdentifierAttributionConflictError`) en 409, le type ou la valeur refusés (`ValidationError`) en 422.
    """
    result = persons.add_identifier(person_id, data.id_type, data.id_value)
    if result.outcome is AttributionOutcome.ALREADY_EXISTS:
        return AddIdentifierResponse(added=False, reason="already_exists")
    return AddIdentifierResponse(
        added=True,
        id_type=data.id_type,
        id_value=result.id_value,
        reassigned=result.outcome is AttributionOutcome.REASSIGNED or None,
    )


# ── Une personne : exclusion, renommage, fusion, distinction, détachement ─


@router.patch("/{person_id}/exclusion", response_model=OkResponse)
def set_person_exclusion(
    person_id: int,
    body: SetPersonExclusion,
    persons: PersonService = Depends(person_service),
) -> OkResponse:
    """Exclut une personne pour le motif donné, ou la retient avec `exclusion: null`.

    Renvoie 404 sur une personne introuvable (`set_exclusion`).
    """
    persons.set_exclusion(person_id, body.exclusion)
    return OkResponse()


@router.patch("/{person_id}/name", response_model=OkResponse)
def update_person_name(
    person_id: int,
    body: UpdatePersonName,
    persons: PersonService = Depends(person_service),
) -> OkResponse:
    """Modifie le nom et le prénom d'une personne.

    Renvoie 422 sans nom de famille, 404 sur une personne introuvable (`update_name`).
    """
    persons.update_name(person_id, body.last_name, body.first_name)
    return OkResponse()


@router.post("/{person_id}/merge", response_model=MergeResponse)
def merge_persons(
    person_id: int,
    body: MergeRequest,
    persons: PersonService = Depends(person_service),
) -> MergeResponse:
    """Fusionne une autre personne (source) dans celle-ci (target).

    Si seule la source a une fiche RH, les rôles s'inversent : la réponse donne les rôles appliqués. Renvoie 422 sur deux identifiants égaux, 404 sur une personne introuvable, 409 si les deux ont une fiche RH (`merge_person`).
    """
    target_id, source_id = persons.merge_person(person_id, body.source_id)
    return MergeResponse(merged=True, source_id=source_id, target_id=target_id)


@router.delete("/{person_id}/distinct-persons/{other_id}", response_model=OkResponse)
def unmark_persons_distinct(
    person_id: int,
    other_id: int,
    persons: PersonService = Depends(person_service),
) -> OkResponse:
    """Annule la décision qui déclare les deux personnes distinctes : les files de triage peuvent de nouveau présenter la paire."""
    persons.unmark_distinct(person_id, other_id)
    return OkResponse()


@router.post("/{person_id}/detach-contributions", response_model=DetachContributionsResponse)
def detach_contributions(
    person_id: int,
    body: DetachContributions,
    persons: PersonService = Depends(person_service),
) -> DetachContributionsResponse:
    """Rejette durablement les paires (publication, personne) des contributions sources choisies, et supprime les formes de nom devenues sans objet."""
    return DetachContributionsResponse.model_validate(
        persons.detach_contributions(
            person_id,
            [
                {"source": a.source, "source_contribution_id": a.source_contribution_id}
                for a in body.contributions
            ],
        )
    )


@router.patch("/{person_id}/name-forms/status", response_model=NameFormStatusResponse)
def update_name_form_status(
    person_id: int,
    body: UpdateNameFormStatus,
    persons: PersonService = Depends(person_service),
) -> NameFormStatusResponse:
    """Met à jour le statut d'une forme de nom : `pending`, `confirmed` ou `rejected`.

    Une forme rejetée sort durablement du rattachement par nom ; les contributions de la personne rattachées par le nom sous cette forme sont marquées pour la redécision de leur personne, au run suivant. Une forme confirmée valide le lien, et corrobore les rattachements par identifiant, faits sans test du nom.
    """
    row = persons.update_name_form_status(person_id, body.name_form, body.status)
    return NameFormStatusResponse(**row)
