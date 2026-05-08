"""
Service Référentiel Personnes — accès exclusif en écriture aux tables
`persons`, `person_identifiers`, `person_name_forms`.

Gère aussi le rattachement/détachement des authorships sources
(source_authorships) puisque le person_id y est la source de vérité
du lien personne.

Les auteurs sources sont dans la table unifiée `source_persons`
(UNIQUE(source, source_id)), les authorships utilisent `source_person_id`.

Variantes async migrées en SQLAlchemy Core (sous-phase 2.6 du chantier
sqlalchemy-core-adoption) : reçoivent une `AsyncConnection` SA. La face
sync (`create_person`, `merge_person`, `add_identifier`, etc.) reste sur
curseur psycopg jusqu'à Phase 4.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from application.audit import async_emit_event, emit_event
from application.authorships import async_delete_orphan_authorships
from domain.errors import ValidationError
from domain.names import compute_person_name_forms
from domain.persons.merge import check_can_merge_persons
from domain.ports.audit_repository import AsyncAuditRepository, AuditRepository
from domain.ports.authorship_repository import AsyncAuthorshipRepository
from domain.ports.person_repository import AsyncPersonRepository, PersonRepository
from domain.sources import ALL_SOURCES_SET

__all__ = [
    # Fonctions utilisées par le pipeline/CLI (+ variante async pour l'API)
    "create_person",
    "async_create_person",
    "merge_person",
    "async_merge_person",
    "add_identifier",
    "async_add_identifier",
    "add_identifiers_from_authorships",
    "add_name_form",
    "link_authorship",
    "link_authorships",
    "refresh_person_name_forms",
    "unlink_authorship",
    # Fonctions API-only (async uniquement)
    "assign_orphan_authorship",
    "batch_assign_orphan_authorships",
    "detach_authorships",
    "detach_name_form",
    "mark_distinct",
    "reassign_identifier",
    "remove_identifier",
    "set_rejected",
    "update_identifier_status",
    "update_name",
]


# ── Création ──


def create_person(cur: Any, last_name: str, first_name: str = "", *, repo: PersonRepository) -> int:
    """Crée une personne et retourne son id."""
    person_id = repo.create(last_name, first_name)
    repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))
    return person_id


async def async_create_person(
    conn: AsyncConnection, last_name: str, first_name: str = "", *, repo: AsyncPersonRepository
) -> int:
    """Variante async de `create_person`."""
    person_id = await repo.create(last_name, first_name)
    await repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))
    return person_id


async def set_rejected(
    conn: AsyncConnection,
    person_id: int,
    rejected: bool,
    *,
    repo: AsyncPersonRepository,
    audit_repo: AsyncAuditRepository | None = None,
) -> None:
    """Marque ou démarque une personne comme rejetée (fausse entité).

    Lève NotFoundError si la personne n'existe pas.
    """
    await repo.set_rejected(person_id, rejected)
    await async_emit_event(
        audit_repo, "person.rejected", "person", person_id, {"rejected": rejected}
    )


async def update_name(
    conn: AsyncConnection,
    person_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: AsyncPersonRepository,
) -> None:
    """Met à jour le nom/prénom d'une personne et rafraîchit ses formes de nom.

    Lève NotFoundError si la personne n'existe pas.
    """
    await repo.update_name(person_id, last_name, first_name)
    await repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))


# ── Rattachement / détachement authorships ──


def link_authorship(
    cur: Any,
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    source_person_id: int | None = None,
    has_hal_person_id: bool = False,
    repo: PersonRepository,
) -> None:
    """Rattache une authorship source à une personne (pipeline).

    Pour HAL avec un compte HAL, fait aussi le dual-write sur source_persons
    (propagation attendue par l'étape 0 du pipeline).
    """
    if source not in ALL_SOURCES_SET:
        return
    repo.link_authorship(
        person_id,
        source,
        authorship_id,
        source_person_id=source_person_id,
        has_hal_person_id=has_hal_person_id,
    )


def link_authorships(
    cur: Any, person_id: int, authorships: list[dict], *, repo: PersonRepository
) -> None:
    """Rattache un groupe d'authorships à une personne (pipeline).

    Chaque dict doit avoir 'source' et 'authorship_id',
    et optionnellement 'source_person_id' et 'has_hal_person_id'.
    """
    for a in authorships:
        link_authorship(
            cur,
            person_id,
            a["source"],
            a["authorship_id"],
            source_person_id=a.get("source_person_id"),
            has_hal_person_id=a.get("has_hal_person_id", False),
            repo=repo,
        )


def unlink_authorship(
    cur: Any, person_id: int, source: str, authorship_id: int, *, repo: PersonRepository
) -> None:
    """Détache une authorship source d'une personne (met person_id à NULL)."""
    if source in ALL_SOURCES_SET:
        repo.unlink_authorship(person_id, source, authorship_id)


# ── Identifiants ──


def add_identifier(
    cur: Any,
    person_id: int,
    id_type: str,
    id_value: str,
    source: str = "auto",
    status: str = "pending",
    *,
    repo: PersonRepository,
) -> None:
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

    Si l'identifiant existe avec statut 'rejected', le réattribue
    (nouveau person_id, statut pending). Si 'pending' ou 'confirmed',
    ne fait rien.
    """
    repo.add_identifier(person_id, id_type, id_value, source, status)


async def async_add_identifier(
    conn: AsyncConnection,
    person_id: int,
    id_type: str,
    id_value: str,
    source: str = "auto",
    status: str = "pending",
    *,
    repo: AsyncPersonRepository,
) -> None:
    """Variante async de `add_identifier`."""
    await repo.add_identifier(person_id, id_type, id_value, source, status)


async def remove_identifier(
    conn: AsyncConnection,
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    repo: AsyncPersonRepository,
    audit_repo: AsyncAuditRepository | None = None,
) -> None:
    """Supprime un identifiant d'une personne.

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    await repo.remove_identifier(person_id, id_type, id_value)
    await async_emit_event(
        audit_repo,
        "person_identifier.removed",
        "person",
        person_id,
        {"id_type": id_type, "id_value": id_value},
    )


async def update_identifier_status(
    conn: AsyncConnection,
    ident_id: int,
    status: str,
    *,
    repo: AsyncPersonRepository,
    audit_repo: AsyncAuditRepository | None = None,
) -> dict:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected).

    Retourne la ligne {id, status} mise à jour.
    Lève NotFoundError si l'identifiant n'existe pas.
    """
    row = await repo.update_identifier_status(ident_id, status)
    await async_emit_event(
        audit_repo,
        "person_identifier.status_changed",
        "person",
        row["person_id"],
        {"ident_id": ident_id, "status": status},
    )
    return {"id": row["id"], "status": row["status"]}


async def reassign_identifier(
    conn: AsyncConnection,
    ident_id: int,
    target_person_id: int,
    *,
    repo: AsyncPersonRepository,
    audit_repo: AsyncAuditRepository | None = None,
) -> None:
    """Réattribue un identifiant à une autre personne (status → pending).

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    await repo.reassign_identifier(ident_id, target_person_id)
    await async_emit_event(
        audit_repo,
        "person_identifier.reassigned",
        "person",
        target_person_id,
        {"ident_id": ident_id},
    )


def add_identifiers_from_authorships(
    cur: Any, person_id: int, authorships: list[dict], *, repo: PersonRepository
) -> None:
    """Ajoute les ORCID, idHAL et IdRef trouvés dans un groupe d'authorships.

    La ``source`` enregistrée sur ``person_identifiers`` reste à sa valeur
    par défaut (``'auto'``) pour les 3 types : tracer la source d'origine
    n'apporte rien d'exploitable (la valeur n'est pas mise à jour quand
    une autre source confirme plus tard l'identifiant) et la priorité
    Crossref pour les ORCID se gérera côté cascade de matching, pas via
    ce champ.
    """
    seen = set()
    for a in authorships:
        for id_type in ("orcid", "idhal", "idref"):
            value = a.get(id_type)
            if value and (id_type, value) not in seen:
                add_identifier(cur, person_id, id_type, value, repo=repo)
                seen.add((id_type, value))


# ── Formes de noms ──


def refresh_person_name_forms(
    cur: Any,
    person_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: PersonRepository,
) -> None:
    """Recalcule les formes de nom source 'persons' d'une personne.

    Shim : calcule les formes via le domaine et délègue au repository.
    """
    forms = compute_person_name_forms(last_name, first_name)
    repo.refresh_name_forms(person_id, forms)


def add_name_form(
    cur: Any,
    person_id: int,
    full_name: str,
    source: str | None = None,
    *,
    repo: PersonRepository,
) -> None:
    """Ajoute une forme de nom à person_name_forms si elle n'existe pas déjà."""
    repo.add_name_form(person_id, full_name, source=source)


async def detach_name_form(
    conn: AsyncConnection, person_id: int, name_form: str, *, repo: AsyncPersonRepository
) -> None:
    """Détache une personne d'une forme de nom. Supprime la forme si
    person_ids devient vide."""
    await repo.detach_name_form(person_id, name_form)


# ── Rattachement / détachement par auteur source ──
# Ces fonctions opèrent par author_id (pas authorship_id) : elles rattachent
# ou détachent TOUTES les authorships d'un auteur source, propagent vers
# les authorships vérité, et gèrent les identifiants.

# ── Attribution d'authorships orphelines ──


async def assign_orphan_authorship(
    conn: AsyncConnection,
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    repo: AsyncPersonRepository,
) -> bool:
    """Attribue une authorship orpheline (person_id IS NULL) à une personne.

    1. Valide la source
    2. Met person_id sur l'authorship source (seulement si elle est orpheline)
    3. Ajoute la forme de nom (si authorship non exclue)
    4. Crée/met à jour l'authorship vérité + FK source

    Retourne True si l'authorship a été attribuée, False sinon.
    """
    if source not in ALL_SOURCES_SET:
        raise ValidationError(f"Source inconnue : {source}")

    row = await repo.assign_orphan_sa(person_id, source, authorship_id)
    if not row:
        return False

    # Ajouter la forme de nom (sauf si authorship exclue)
    if row["author_name_normalized"] and not row.get("excluded"):
        await repo.add_name_form(person_id, row["author_name_normalized"], source=source)

    # Créer/mettre à jour l'authorship vérité
    await repo.ensure_truth_authorship(person_id, source, authorship_id)
    return True


async def batch_assign_orphan_authorships(
    conn: AsyncConnection, person_id: int, sa_ids: list[int], *, repo: AsyncPersonRepository
) -> int:
    """Attribue en batch plusieurs authorships sources orphelines à une personne.

    Retourne le nombre de source_authorships effectivement rattachées
    (celles qui étaient orphelines).
    """
    return await repo.batch_assign_orphans(person_id, sa_ids)


async def detach_authorships(
    conn: AsyncConnection,
    person_id: int,
    authorships: list[dict],
    name_form: str | None = None,
    *,
    repo: AsyncPersonRepository,
    authorship_repo: AsyncAuthorshipRepository,
) -> dict:
    """Détache un lot d'authorships sources d'une personne et nettoie les
    authorships vérité devenues orphelines.

    Si `name_form` est fourni, supprime aussi la forme de nom de la personne
    lorsque plus aucune authorship ne la porte.

    Retourne {"detached": N, "deleted_authorships": M, "cleaned_form": bool}.
    """
    for a in authorships:
        if a["source"] in ALL_SOURCES_SET:
            await repo.unlink_authorship(person_id, a["source"], a["authorship_id"])

    deleted = await async_delete_orphan_authorships(conn, person_id, repo=authorship_repo)

    cleaned_form = False
    if name_form and await repo.count_authorships_with_name_form(person_id, name_form) == 0:
        await repo.detach_name_form(person_id, name_form)
        cleaned_form = True

    return {
        "detached": len(authorships),
        "deleted_authorships": deleted,
        "cleaned_form": cleaned_form,
    }


# ── Fusion ──


async def mark_distinct(
    conn: AsyncConnection,
    person_id_a: int,
    person_id_b: int,
    *,
    repo: AsyncPersonRepository,
    audit_repo: AsyncAuditRepository | None = None,
) -> None:
    """Marque deux personnes comme distinctes (non-doublon) dans
    `distinct_persons`. Idempotent.

    Les IDs sont triés pour garantir l'unicité de la paire.
    """
    inserted = await repo.mark_distinct(person_id_a, person_id_b)
    # Audit seulement si une ligne a été insérée (la paire n'existait pas déjà)
    if inserted:
        await async_emit_event(
            audit_repo,
            "person.marked_distinct",
            "person",
            inserted[0],
            {"other_id": inserted[1]},
        )


def merge_person(
    cur: Any,
    target_id: int,
    source_id: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la personne `source_id` dans `target_id`.

    Invariant métier : refus si les deux personnes ont chacune une
    fiche RH distincte (risque de perdre de l'information humaine).

    Lève ConflictError si l'invariant est violé. Émet un événement
    d'audit `person.merged` si l'utilisateur est dans le contexte.
    """
    check_can_merge_persons(repo.has_distinct_rh(target_id, source_id), target_id, source_id)
    repo.merge_into(target_id, source_id)
    emit_event(audit_repo, "person.merged", "person", target_id, {"source_id": source_id})


async def async_merge_person(
    conn: AsyncConnection,
    target_id: int,
    source_id: int,
    *,
    repo: AsyncPersonRepository,
    audit_repo: AsyncAuditRepository | None = None,
) -> None:
    """Variante async de `merge_person`."""
    check_can_merge_persons(await repo.has_distinct_rh(target_id, source_id), target_id, source_id)
    await repo.merge_into(target_id, source_id)
    await async_emit_event(
        audit_repo, "person.merged", "person", target_id, {"source_id": source_id}
    )
