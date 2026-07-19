"""Router des personnes : annuaire, profil, files de triage et gestes de curation. Sert `/api/persons/*`.

Les lectures passent par le port `PersonsQueries`, les écritures par les command handlers de `application.services.persons.commands`. Les gestes qui portent sur les signatures elles-mêmes vivent dans `authorships.py`.

L'ordre de déclaration porte une contrainte : les chemins littéraux — `/directory`, `/search`, `/facets`, `/stats`, les quatre files de triage, le registre des identifiants — précèdent tous `/{person_id}`, qui accepterait n'importe lequel d'entre eux comme identifiant.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.persons_queries import (
    AmbiguousNameFormsResponse,
    DetachableIntrudersResponse,
    DirectoryFilters,
    FacetFilters,
    IdentifierConflictsResponse,
    ListFilters,
    NameDuplicatesResponse,
    NameFormAuthorshipsResponse,
    PersonAddressesResponse,
    PersonDashboardResponse,
    PersonDirectoryResponse,
    PersonDirectorySort,
    PersonListResponse,
    PersonListSort,
    PersonOut,
    PersonProfileResponse,
    PersonSearchResult,
    PersonsFacetsResponse,
    PersonsQueries,
    PersonsStatsResponse,
    PersonThesesResponse,
    SharingPersonOut,
)
from application.ports.api.subjects_queries import SubjectFrequency
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.persons import commands as person_commands
from application.services.persons.core import AddIdentifierOutcome
from interfaces.api.deps import (
    audit_repo,
    authorship_repo,
    db_conn,
    person_repo,
    persons_queries,
)
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    AddIdentifier,
    AddIdentifierResponse,
    DetachAuthorships,
    DetachAuthorshipsResponse,
    IdentifierReassignResponse,
    IdentifierStatusResponse,
    MarkDistinctPersons,
    MergeRequest,
    MergeResponse,
    NameFormStatusResponse,
    OkResponse,
    ReassignIdentifier,
    RejectPerson,
    RemovedResponse,
    TotalCountResponse,
    UpdateIdentifierStatus,
    UpdateNameFormStatus,
    UpdatePersonName,
)
from interfaces.api.params import TOP_SUBJECTS_LIMIT, TopSubjectsLimit

router = APIRouter(prefix="/api/persons", tags=["persons"])


# ── Listes et facettes ───────────────────────────────────────────


@router.get("/directory", response_model=PersonDirectoryResponse)
def persons_directory(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: bool | None = Query(None),
    has_idhal: bool | None = Query(None),
    has_idref: bool | None = Query(None),
    has_rh: bool | None = Query(None),
    lab_id: int | None = Query(None),
    sort: PersonDirectorySort = Query("name_asc"),
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonDirectoryResponse:
    """Annuaire public des personnes du périmètre, avec leurs ORCID et idHAL.

    `lab_id` restreint l'annuaire aux personnes d'un laboratoire : l'onglet personnes de la fiche d'un laboratoire s'en sert, plutôt que d'un endpoint qui lui serait propre.
    """
    filters = DirectoryFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        lab_id=lab_id,
    )
    return queries.persons_directory(filters=filters, page=page, per_page=per_page, sort=sort)


@router.get("/search", response_model=list[PersonSearchResult])
def search_persons(
    q: str = Query("", min_length=2),
    limit: int = Query(10, ge=1, le=30),
    queries: PersonsQueries = Depends(persons_queries),
) -> list[PersonSearchResult]:
    """Recherche rapide de personnes (autocomplete)."""
    return queries.search_persons(q=q, limit=limit)


@router.get("", response_model=PersonListResponse)
def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: bool | None = Query(None),
    has_idhal: bool | None = Query(None),
    has_idref: bool | None = Query(None),
    has_rh: bool | None = Query(None),
    has_pending_forms: bool | None = Query(None),
    has_pending_identifiers: bool | None = Query(None),
    sort: PersonListSort = Query("name_asc"),
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonListResponse:
    """Liste des personnes avec filtres (curation).

    `department` et `role` acceptent plusieurs valeurs séparées par des virgules, selon la même convention que l'annuaire et les facettes.
    """
    filters = ListFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        has_pending_forms=has_pending_forms,
        has_pending_identifiers=has_pending_identifiers,
    )
    return queries.list_persons(filters=filters, page=page, per_page=per_page, sort=sort)


@router.get("/facets", response_model=PersonsFacetsResponse)
def persons_facets(
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: bool | None = Query(None),
    has_idhal: bool | None = Query(None),
    has_idref: bool | None = Query(None),
    has_rh: bool | None = Query(None),
    has_pending_forms: bool | None = Query(None),
    has_pending_identifiers: bool | None = Query(None),
    lab_id: int | None = Query(None),
    search: str = Query(""),
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonsFacetsResponse:
    """Facettes dynamiques pour la page personnes (scopables à un labo via `lab_id`)."""
    filters = FacetFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        has_pending_forms=has_pending_forms,
        has_pending_identifiers=has_pending_identifiers,
        lab_id=lab_id,
    )
    return queries.persons_facets(filters=filters)


@router.get("/stats", response_model=PersonsStatsResponse)
def persons_stats(
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonsStatsResponse:
    """Statistiques sur les personnes et l'alignement."""
    return queries.persons_stats()


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
    """Formes de nom portées par ≥2 personnes avec ≥1 lien pending, paginées."""
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

    Ce sont des doublons probables ou des erreurs d'attribution, que la curation tranche à l'œil.
    """
    return queries.identifier_conflicts(page=page, per_page=per_page)


@router.get("/detachable-intruders/count", response_model=TotalCountResponse)
def detachable_intruders_count(
    queries: PersonsQueries = Depends(persons_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Intrus détachables » (badge)."""
    return TotalCountResponse(total=queries.detachable_intruders_count())


@router.get("/detachable-intruders", response_model=DetachableIntrudersResponse)
def detachable_intruders(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries),
) -> DetachableIntrudersResponse:
    """Personnes rattachées à deux signatures ou plus d'une même publication, avec leur ancre et leur intrus, paginées.

    L'intrus se détache en rejetant sa forme de nom, par `PATCH /api/persons/{id}/name-forms/status`.
    """
    return queries.detachable_intruders(page=page, per_page=per_page)


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
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Marque deux personnes comme distinctes : les files de triage par nom et par identifiant écartent la paire.

    Renvoie 400 sur deux identifiants égaux (`mark_distinct`).
    """
    person_commands.mark_distinct(
        conn, body.person_id_a, body.person_id_b, repo=repo, audit_repo=audit
    )
    return OkResponse()


# ── Registre des identifiants ────────────────────────────────────


@router.patch("/identifiers/{ident_id}/status", response_model=IdentifierStatusResponse)
def update_identifier_status(
    ident_id: int,
    body: UpdateIdentifierStatus,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> IdentifierStatusResponse:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected)."""
    row = person_commands.update_identifier_status(
        conn, ident_id, body.status, repo=repo, audit_repo=audit
    )
    return IdentifierStatusResponse(id=row["id"], status=row["status"])


@router.patch("/identifiers/{ident_id}/reassign", response_model=IdentifierReassignResponse)
def reassign_identifier(
    ident_id: int,
    body: ReassignIdentifier,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> IdentifierReassignResponse:
    """Réattribue un identifiant rejeté à une autre personne (status → pending).

    Renvoie 404 sur un identifiant ou une personne cible introuvable (`reassign_identifier`).
    """
    person_commands.reassign_identifier(conn, ident_id, body.person_id, repo=repo, audit_repo=audit)
    return IdentifierReassignResponse(id=ident_id, person_id=body.person_id, status="pending")


# ── Une personne : lectures ──────────────────────────────────────


@router.get("/{person_id}", response_model=PersonProfileResponse)
def person_profile(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonProfileResponse:
    """Profil public complet d'une personne."""
    profile = queries.person_profile(person_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Personne introuvable")
    return profile


@router.get("/{person_id}/curation", response_model=PersonOut)
def person_curation(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonOut:
    """Une personne sous la projection de la liste de curation : drapeau de rejet, identifiants avec leur statut et leur source, formes de nom avec leur état d'arbitrage.

    Alimente le panneau latéral ouvert directement par son URL, hors de la liste qui porte normalement ces données.
    """
    person = queries.person_admin(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Personne introuvable")
    return person


@router.get("/{person_id}/theses", response_model=PersonThesesResponse)
def person_theses(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonThesesResponse:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    return queries.person_theses(person_id)


@router.get("/{person_id}/addresses", response_model=PersonAddressesResponse)
def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonAddressesResponse:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    return queries.person_addresses(person_id, page=page, per_page=per_page)


@router.get("/{person_id}/dashboard", response_model=PersonDashboardResponse)
def person_dashboard(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> PersonDashboardResponse:
    """Dashboard personne : publis/an + Open Access."""
    return queries.person_dashboard(person_id)


@router.get("/{person_id}/subjects", response_model=list[SubjectFrequency])
def person_subjects(
    person_id: int,
    limit: TopSubjectsLimit = TOP_SUBJECTS_LIMIT,
    queries: PersonsQueries = Depends(persons_queries),
) -> list[SubjectFrequency]:
    """Top sujets des publications de cette personne (nuage de mots)."""
    return queries.person_subjects(person_id, limit=limit)


@router.get("/{person_id}/sharing-name-forms", response_model=list[SharingPersonOut])
def persons_sharing_name_form(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries),
) -> list[SharingPersonOut]:
    """Personnes partageant ≥1 forme de nom avec celle-ci (candidates à l'absorption)."""
    return queries.persons_sharing_name_form(person_id)


@router.get("/{person_id}/name-form-authorships", response_model=NameFormAuthorshipsResponse)
def name_form_authorships(
    person_id: int,
    name_form: str = Query(...),
    queries: PersonsQueries = Depends(persons_queries),
) -> NameFormAuthorshipsResponse:
    """Authorships sources + autres personnes partageant une forme de nom."""
    return queries.name_form_authorships(person_id, name_form)


# ── Une personne : identifiants ──────────────────────────────────


@router.post("/{person_id}/identifiers", response_model=AddIdentifierResponse)
def add_person_identifier(
    person_id: int,
    data: AddIdentifier,
    conn: Connection = Depends(db_conn),
    queries: PersonsQueries = Depends(persons_queries),
    repo: PersonRepository = Depends(person_repo),
) -> AddIdentifierResponse:
    """Ajoute à la main un identifiant (ORCID, idHAL ou IdRef) à une personne.

    La cascade de décision — insertion, idempotence, réattribution, conflit — appartient à `add_identifier`, appelé avec `source="manual"` : il refuse alors les types qu'aucun humain n'attribue, et vérifie l'existence de la personne. Le router traduit l'issue en réponse. Les handlers globaux traduisent la personne absente (`NotFoundError`) en 404, le conflit (`CannotAttributeConflict`) en 409, le type ou la valeur refusés (`ValidationError`) en 400.
    """
    result = person_commands.add_identifier(
        conn, person_id, data.id_type, data.id_value, source="manual", repo=repo
    )
    if result.outcome is AddIdentifierOutcome.ALREADY_EXISTS:
        return AddIdentifierResponse(added=False, reason="already_exists")
    return AddIdentifierResponse(
        added=True,
        id_type=data.id_type,
        id_value=result.id_value,
        reassigned=True if result.outcome is AddIdentifierOutcome.REASSIGNED else None,
    )


@router.delete("/{person_id}/identifiers/{id_type}/{id_value:path}", response_model=RemovedResponse)
def remove_person_identifier(
    person_id: int,
    id_type: str,
    id_value: str,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> RemovedResponse:
    """Supprime un identifiant d'une personne."""
    person_commands.remove_identifier(
        conn, person_id, id_type, id_value, repo=repo, audit_repo=audit
    )
    return RemovedResponse()


# ── Une personne : rejet, renommage, fusion, détachement ─────────


@router.patch("/{person_id}/reject", response_model=OkResponse)
def reject_person(
    person_id: int,
    body: RejectPerson,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Marque/démarque une personne comme rejetée."""
    person_commands.set_rejected(conn, person_id, body.rejected, repo=repo, audit_repo=audit)
    return OkResponse()


@router.patch("/{person_id}/name", response_model=OkResponse)
def update_person_name(
    person_id: int,
    body: UpdatePersonName,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
) -> OkResponse:
    """Modifie le nom/prénom d'une personne.

    Renvoie 400 sans patronyme, 404 sur une personne introuvable (`update_name`).
    """
    person_commands.update_name(conn, person_id, body.last_name, body.first_name, repo=repo)
    return OkResponse()


@router.post("/{person_id}/merge", response_model=MergeResponse)
def merge_persons(
    person_id: int,
    body: MergeRequest,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> MergeResponse:
    """Fusionne une autre personne (source) dans celle-ci (target).

    Renvoie 400 sur deux identifiants égaux, 404 sur une personne introuvable, 409 si chacune porte une fiche RH distincte (`merge_person`).
    """
    person_commands.merge_person(conn, person_id, body.source_id, repo=repo, audit_repo=audit)
    return MergeResponse(merged=True, source_id=body.source_id, target_id=person_id)


@router.post("/{person_id}/detach-authorships", response_model=DetachAuthorshipsResponse)
def detach_authorships(
    person_id: int,
    body: DetachAuthorships,
    conn: Connection = Depends(db_conn),
    person_repo_: PersonRepository = Depends(person_repo),
    auth_repo: AuthorshipRepository = Depends(authorship_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> DetachAuthorshipsResponse:
    """Rejette durablement les paires (publication, personne) des signatures sources choisies, et nettoie les formes de nom devenues sans objet."""
    return DetachAuthorshipsResponse.model_validate(
        person_commands.detach_authorships(
            conn,
            person_id,
            [{"source": a.source, "authorship_id": a.authorship_id} for a in body.authorships],
            repo=person_repo_,
            authorship_repo=auth_repo,
            audit_repo=audit,
        )
    )


@router.patch("/{person_id}/name-forms/status", response_model=NameFormStatusResponse)
def update_name_form_status(
    person_id: int,
    body: UpdateNameFormStatus,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    auth_repo: AuthorshipRepository = Depends(authorship_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> NameFormStatusResponse:
    """Met à jour le statut d'une forme de nom : `pending`, `confirmed` ou `rejected`.

    `rejected` pose un verrou durable et détache les signatures qui portent la forme : leur `person_id` est vidé dans `source_authorships`, et les signatures consolidées devenues orphelines sont supprimées. `confirmed` valide le lien et corrobore les rapprochements faits par identifiant, qui n'éprouvent pas le nom.
    """
    row = person_commands.update_name_form_status(
        conn,
        person_id,
        body.name_form,
        body.status,
        repo=repo,
        authorship_repo=auth_repo,
        audit_repo=audit,
    )
    return NameFormStatusResponse(**row)
