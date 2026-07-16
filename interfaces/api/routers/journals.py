"""Router /api/journals/* — les revues : listes, recherche, édition, fusion."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.journals_queries import (
    JournalDashboardResponse,
    JournalDetailResponse,
    JournalListResponse,
    JournalQueries,
    JournalsFacetsResponse,
)
from application.ports.api.subjects_queries import SubjectFrequency
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdate
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.journals import commands as journal_commands
from application.services.journals.core import requalify_publications_for_journal
from domain.journals.journal import (
    JOURNAL_TYPE_LABELS_FR,
    JOURNAL_TYPES,
    JOURNAL_TYPES_SET,
    OA_MODEL_LABELS_FR,
    OA_MODELS,
)
from interfaces.api.deps import (
    audit_repo,
    db_conn,
    journal_queries,
    journal_repo,
    metadata_correction_queries,
    publication_repo,
)
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    EnumOption,
    JournalTypeChangeImpact,
    MergeRequest,
    MergeResponse,
    OkResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/journals/oa-models", response_model=list[EnumOption])
def list_oa_models() -> list[EnumOption]:
    """Valeurs possibles de `oa_model` avec leur libellé français.

    La source de vérité côté Python est `domain.journals.journal.OA_MODELS` et `OA_MODEL_LABELS_FR`. Alimente la facette « Modèle OA » des listes de revues et la liste déroulante de la modale d'édition admin.
    """
    return [EnumOption(value=v, label_fr=OA_MODEL_LABELS_FR[v]) for v in OA_MODELS]


@router.get("/api/journal-types", response_model=list[EnumOption])
def list_journal_types() -> list[EnumOption]:
    """Valeurs possibles de l'enum `journal_type` avec leur libellé français.

    La source de vérité côté Python est `domain.journals.journal.JOURNAL_TYPES` et `JOURNAL_TYPE_LABELS_FR`, dont un test d'intégration vérifie l'accord avec l'enum SQL. Alimente la liste déroulante de la page admin des revues et la colonne « Type » des pages publiques.
    """
    return [EnumOption(value=v, label_fr=JOURNAL_TYPE_LABELS_FR[v]) for v in JOURNAL_TYPES]


@router.get("/api/journals/facets", response_model=JournalsFacetsResponse)
def journals_facets(
    search: str | None = None,
    publisher_id: int | None = None,
    journal_type: str = Query(""),
    is_in_doaj: bool | None = None,
    oa_model: str = Query(""),
    with_pubs: bool = False,
    queries: JournalQueries = Depends(journal_queries),
) -> JournalsFacetsResponse:
    """Comptes par option des facettes de la liste des revues.

    Convention partagée avec `/api/publications/facets` : chaque facette écarte sa propre dimension de la clause WHERE, de sorte que son décompte annonce le nombre de revues atteignables si l'option était cochée ou décochée.
    """
    return queries.journals_facets(
        search=search,
        publisher_id=publisher_id,
        journal_types=parse_str_csv(journal_type),
        is_in_doaj=is_in_doaj,
        oa_models=parse_str_csv(oa_model),
        with_pubs=with_pubs,
    )


@router.get("/api/journals", response_model=JournalListResponse)
def list_journals(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    publisher_id: int | None = None,
    journal_type: str = Query(""),
    is_in_doaj: bool | None = None,
    oa_model: str = Query(""),
    with_pubs: bool = False,
    sort: str = "title",
    queries: JournalQueries = Depends(journal_queries),
) -> JournalListResponse:
    """Liste paginée des revues, avec le décompte de leurs publications.

    Filtres :

    - `search` : insensible à la casse sur le titre normalisé, ignoré en deçà de deux caractères.
    - `publisher_id` : égalité stricte.
    - `journal_type` et `oa_model` : valeurs séparées par des virgules (par exemple `journal,proceedings`), vide valant absence de filtre, selon la convention multi-valeurs de `/api/publications`.
    - `is_in_doaj` : booléen ; omis, il ne filtre rien.
    - `with_pubs` : restreint aux revues portant au moins une publication. La page publique s'en sert pour masquer les revues orphelines, que l'admin garde la possibilité de voir.

    `sort` accepte `title`, `publisher` et `pubs`, préfixés d'un tiret pour l'ordre descendant, et retombe sur `title` devant une valeur inconnue.
    """
    return queries.list_journals(
        search=search,
        publisher_id=publisher_id,
        journal_types=parse_str_csv(journal_type),
        is_in_doaj=is_in_doaj,
        oa_models=parse_str_csv(oa_model),
        with_pubs=with_pubs,
        sort=sort,
        page=page,
        per_page=per_page,
    )


@router.get("/api/journals/{journal_id}", response_model=JournalDetailResponse)
def get_journal(
    journal_id: int,
    queries: JournalQueries = Depends(journal_queries),
) -> JournalDetailResponse:
    """Profil complet d'une revue, pour sa page publique.

    Porte ses métadonnées, la réponse DOAJ brute et sa date d'import, et le décompte de ses publications. Renvoie 404 sur une revue inconnue.
    """
    row = queries.get_journal_detail(journal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Revue introuvable")
    return row


@router.get("/api/journals/{journal_id}/dashboard", response_model=JournalDashboardResponse)
def get_journal_dashboard(
    journal_id: int,
    queries: JournalQueries = Depends(journal_queries),
) -> JournalDashboardResponse:
    """Agrégats des publications de la revue : distributions de `doc_type` et de `oa_status`.

    Sert l'onglet tableau de bord de la page d'une revue, où ces distributions donnent à voir les incohérences — un `article` dans une revue de type `proceedings`, par exemple. Renvoie 404 sur une revue inconnue.
    """
    result = queries.get_journal_dashboard(journal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Revue introuvable")
    return result


@router.get("/api/journals/{journal_id}/subjects", response_model=list[SubjectFrequency])
def get_journal_subjects(
    journal_id: int,
    limit: int = Query(30, ge=1, le=200),
    queries: JournalQueries = Depends(journal_queries),
) -> list[SubjectFrequency]:
    """Sujets les plus fréquents des publications de la revue, pour l'onglet tableau de bord.

    Les sujets génériques, dont l'`usage_count` dépasse 5000, sont écartés : ils noieraient les autres. Une revue sans publication indexée donne une liste vide.
    """
    return queries.get_journal_subjects(journal_id, limit=limit)


@router.get(
    "/api/journals/{journal_id}/type-change-impact",
    response_model=JournalTypeChangeImpact,
)
def get_type_change_impact(
    journal_id: int,
    new_type: str = Query(...),
    conn: Connection = Depends(db_conn),
    repo: JournalRepository = Depends(journal_repo),
    pub_repo: PublicationRepository = Depends(publication_repo),
    correction_queries: MetadataCorrectionQueries = Depends(metadata_correction_queries),
) -> JournalTypeChangeImpact:
    """Compte les publications de la revue dont le `doc_type` changerait si son `journal_type` passait à `new_type`.

    L'aperçu applique réellement le changement — écriture du type, recalcul des corrections sur les publications sources, rafraîchissement — dans un `SAVEPOINT` annulé ensuite. Il emprunte donc le chemin exact de l'édition, et aucune écriture ne survit.
    """
    if new_type not in JOURNAL_TYPES_SET:
        raise HTTPException(status_code=400, detail=f"journal_type inconnu : {new_type}")
    savepoint = conn.begin_nested()
    try:
        repo.update_journal_fields(journal_id, JournalUpdate(journal_type=new_type))
        count = requalify_publications_for_journal(
            journal_id,
            conn=conn,
            correction_queries=correction_queries,
            pub_repo=pub_repo,
        )
    finally:
        savepoint.rollback()
    return JournalTypeChangeImpact(count=count)


@router.put("/api/journals/{journal_id}", response_model=OkResponse)
def update_journal(
    journal_id: int,
    body: JournalUpdate,
    conn: Connection = Depends(db_conn),
    repo: JournalRepository = Depends(journal_repo),
    pub_repo: PublicationRepository = Depends(publication_repo),
    audit: AuditRepository = Depends(audit_repo),
    correction_queries: MetadataCorrectionQueries = Depends(metadata_correction_queries),
) -> OkResponse:
    """Met à jour une revue, champ par champ.

    Seuls les champs présents dans le corps de la requête sont écrits (`exclude_unset=True`). Renvoie 404 sur une revue inconnue.

    Un `journal_type` qui change de valeur entraîne la requalification du `doc_type` des publications rattachées, dans la même transaction (`requalify_publications_for_journal`). L'endpoint `type-change-impact` en donne l'ampleur avant confirmation.
    """
    journal_commands.update_journal(
        conn,
        journal_id,
        update=body,
        repo=repo,
        pub_repo=pub_repo,
        audit_repo=audit,
        correction_queries=correction_queries,
    )
    return OkResponse()


@router.post("/api/journals/{journal_id}/merge", response_model=MergeResponse)
def merge(
    journal_id: int,
    body: MergeRequest,
    conn: Connection = Depends(db_conn),
    queries: JournalQueries = Depends(journal_queries),
    repo: JournalRepository = Depends(journal_repo),
    pub_repo: PublicationRepository = Depends(publication_repo),
    audit: AuditRepository = Depends(audit_repo),
    correction_queries: MetadataCorrectionQueries = Depends(metadata_correction_queries),
) -> MergeResponse:
    """Fusionne la revue `source_id` dans la revue `journal_id`.

    Les publications et les métadonnées de la source passent à la cible, puis la source est supprimée. Les publications absorbées sont requalifiées contre le `journal_type` de la cible (`merge_journals`). Renvoie 404 si l'une des deux revues est introuvable.
    """
    found = queries.existing_journal_ids((journal_id, body.source_id))
    if journal_id not in found:
        raise HTTPException(status_code=404, detail="Revue cible introuvable")
    if body.source_id not in found:
        raise HTTPException(status_code=404, detail="Revue source introuvable")

    journal_commands.merge_journals(
        conn,
        journal_id,
        body.source_id,
        correction_queries=correction_queries,
        repo=repo,
        pub_repo=pub_repo,
        audit_repo=audit,
    )
    return MergeResponse(merged=True, source_id=body.source_id, target_id=journal_id)
