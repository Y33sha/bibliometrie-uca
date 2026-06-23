"""Service Référentiel Personnes — accès exclusif en écriture aux tables `persons`, `person_identifiers`, `person_name_forms`.

Gère aussi le rattachement/détachement des authorships sources (`source_authorships`) puisque le `person_id` y est la source de vérité du lien personne.
"""

import logging

from application.audit import emit_event
from application.authorships.core import reject_pair
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import CannotAttributeConflict, NotFoundError
from domain.persons.identifiers import PERSON_IDENTIFIER_TYPES, AttributionStatus
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person_identifier import PersonIdentifier
from domain.sources.registry import ALL_SOURCES_SET

logger = logging.getLogger(__name__)

__all__ = [
    "create_person",
    "merge_person",
    "add_identifier",
    "add_identifiers_from_authorships",
    "add_name_form",
    "link_authorship",
    "link_authorships",
    "refresh_person_name_forms",
    "unlink_authorship",
    "set_rejected",
    "update_name",
    "remove_identifier",
    "update_identifier_status",
    "reassign_identifier",
    "update_name_form_status",
    "detach_authorships",
    "mark_distinct",
]


# ── Création / mise à jour personne ──


def create_person(last_name: str, first_name: str = "", *, repo: PersonRepository) -> int:
    """Crée une personne et retourne son id."""
    person_id = repo.create(last_name, first_name)
    repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))
    return person_id


def set_rejected(
    person_id: int,
    rejected: bool,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Marque ou démarque une personne comme rejetée (fausse entité).

    Lève NotFoundError si la personne n'existe pas.
    """
    repo.set_rejected(person_id, rejected)
    emit_event(audit_repo, "person.rejected", "person", person_id, {"rejected": rejected})


def update_name(
    person_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: PersonRepository,
) -> None:
    """Met à jour le nom/prénom d'une personne et rafraîchit ses formes de nom.

    Lève NotFoundError si la personne n'existe pas.
    """
    repo.update_name(person_id, last_name, first_name)
    repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))


# ── Rattachement / détachement authorships ──


def link_authorship(
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    repo: PersonRepository,
) -> None:
    """Rattache une authorship source à une personne (pipeline)."""
    if source not in ALL_SOURCES_SET:
        return
    repo.link_authorship(person_id, source, authorship_id)


def link_authorships(person_id: int, authorships: list[dict], *, repo: PersonRepository) -> None:
    """Rattache un groupe d'authorships à une personne (pipeline).

    Chaque dict doit avoir 'source' et 'authorship_id'.
    """
    for a in authorships:
        link_authorship(
            person_id,
            a["source"],
            a["authorship_id"],
            repo=repo,
        )


def unlink_authorship(
    person_id: int, source: str, authorship_id: int, *, repo: PersonRepository
) -> None:
    """Détache une authorship source d'une personne (met person_id à NULL)."""
    if source in ALL_SOURCES_SET:
        repo.unlink_authorship(person_id, source, authorship_id)


# ── Identifiants ──


def add_identifier(
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    source: str = "auto",
    repo: PersonRepository,
) -> None:
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

    Charge l'éventuel `PersonIdentifier` existant pour `(id_type, id_value)`
    et dispatche :

    - **absent** → insertion en `pending`
    - **existant sur cette personne** → idempotent (no-op)
    - **existant sur autre personne en `rejected`** → réattribution
      (statut → `pending`, via `PersonIdentifier.reattribute_to`)
    - **existant sur autre personne en `pending` ou `confirmed`** →
      lève `CannotAttributeConflict`. Pour réattribuer, le statut
      existant doit d'abord être passé à `rejected` (via
      `update_identifier_status` ou `reassign_identifier`).
    """
    existing = repo.find_identifier(id_type, id_value)

    if existing is None:
        ident = PersonIdentifier(
            id=None,
            person_id=person_id,
            id_type=id_type,
            id_value=id_value,
            status=AttributionStatus.PENDING,
            source=source,
        )
        repo.insert_identifier(ident)
        return

    if existing.person_id == person_id:
        return  # idempotent

    if existing.status is AttributionStatus.REJECTED:
        existing.reattribute_to(person_id, source=source)
        repo.update_identifier(existing)
        return

    raise CannotAttributeConflict(
        f"Identifiant {id_type}={id_value!r} déjà attribué à person_id={existing.person_id} "
        f"avec statut {existing.status.value!r} ; impossible d'attribuer à person_id={person_id}.",
    )


def remove_identifier(
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Supprime un identifiant d'une personne.

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    repo.remove_identifier(person_id, id_type, id_value)
    emit_event(
        audit_repo,
        "person_identifier.removed",
        "person",
        person_id,
        {"id_type": id_type, "id_value": id_value},
    )


def update_identifier_status(
    ident_id: int,
    status: str,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> dict:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected).

    Retourne la ligne {id, status} mise à jour.
    Lève NotFoundError si l'identifiant n'existe pas.
    """
    row = repo.update_identifier_status(ident_id, status)
    emit_event(
        audit_repo,
        "person_identifier.status_changed",
        "person",
        row["person_id"],
        {"ident_id": ident_id, "status": status},
    )
    return {"id": row["id"], "status": row["status"]}


def reassign_identifier(
    ident_id: int,
    target_person_id: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Réattribue un identifiant à une autre personne (status → pending).

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    repo.reassign_identifier(ident_id, target_person_id)
    emit_event(
        audit_repo,
        "person_identifier.reassigned",
        "person",
        target_person_id,
        {"ident_id": ident_id},
    )


def add_identifiers_from_authorships(
    person_id: int, authorships: list[dict], *, repo: PersonRepository
) -> None:
    """Promotion canonique en batch : pour chaque authorship source, extrait les identifiants observés (orcid/idhal/idref/hal_person_id) et délègue à `add_identifier` qui dispatche selon l'état existant en base.

    Path batch tolérant : un `CannotAttributeConflict` sur un identifiant donné (ORCID déjà attribué en pending/confirmed à une autre personne) est loggé en warning et la promotion continue pour les autres identifiants. Le path strict reste `add_identifier` (singulier) que l'API admin utilise directement.

    Couvre les 4 id_types acceptés en base (`PERSON_IDENTIFIER_TYPES`) : `orcid`, `idhal`, `idref`, `hal_person_id`. Les 3 premiers sont visibles UI ; `hal_person_id` est interne (filtré côté lecture par `PUBLIC_PERSON_IDENTIFIER_TYPES`).

    Spécificité `hal_person_id` : la valeur arrive en `int` depuis la query (cf. `fetch_unlinked_authorships`), on convertit en str pour la table `person_identifiers`.

    La ``source`` enregistrée sur ``person_identifiers`` reste à sa valeur par défaut (``'auto'``) : tracer la source d'origine n'apporte rien d'exploitable (la valeur n'est pas mise à jour quand une autre source confirme plus tard l'identifiant) et la priorité Crossref pour les ORCID se gérera côté cascade de matching, pas via ce champ.
    """
    seen: set[tuple[str, str]] = set()
    for a in authorships:
        for id_type in PERSON_IDENTIFIER_TYPES:
            raw = a.get(id_type)
            if not raw:
                continue
            # int en source côté hal_person_id, str en cible person_identifiers
            value = str(raw) if id_type == "hal_person_id" else raw
            if (id_type, value) in seen:
                continue
            seen.add((id_type, value))
            try:
                add_identifier(person_id, id_type, value, repo=repo)
            except CannotAttributeConflict as exc:
                logger.warning("%s", exc)


# ── Formes de noms ──


def refresh_person_name_forms(
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
    person_id: int,
    full_name: str,
    source: str | None = None,
    *,
    repo: PersonRepository,
) -> None:
    """Ajoute une forme de nom à person_name_forms si elle n'existe pas déjà."""
    repo.add_name_form(person_id, full_name, source=source)


def update_name_form_status(
    person_id: int,
    name_form: str,
    status: str,
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository | None = None,
    audit_repo: AuditRepository | None = None,
) -> dict:
    """Met à jour le statut d'une forme de nom (pending/confirmed/rejected).

    `confirmed` valide le lien. `rejected` est le verrou de non-retour ET déclenche
    le **détachement** des signatures portant cette forme : leurs `source_authorships`
    sont nullées et les `authorships` canoniques devenues sans source sont supprimées
    (le verrou seul n'agirait qu'au matching futur, et la phase persons est incrémentale).

    Retourne la ligne {person_id, name_form, status}. Lève NotFoundError si le couple
    (name_form, person_id) n'existe pas.
    """
    row = repo.update_name_form_status(person_id, name_form, status)
    if status == "rejected":
        detached = repo.null_person_id_for_name_form(person_id, name_form)
        if detached and authorship_repo is not None:
            authorship_repo.delete_orphan_authorships_for_person(person_id)
    emit_event(
        audit_repo,
        "person_name_form.status_changed",
        "person",
        person_id,
        {"name_form": name_form, "status": status},
    )
    return row


def detach_authorships(
    person_id: int,
    authorships: list[dict],
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository | None = None,
) -> dict:
    """Rejette durablement les paires (publication, personne) couvertes par un
    lot d'authorships sources sélectionnées.

    Le rejet porte sur la publication entière : on résout l'ensemble distinct
    des `publication_id` des sources sélectionnées et on applique `reject_pair`
    à chaque paire (enregistrement du rejet, détachement de toutes les sources
    de la paire, suppression de la ligne consolidée). Puis on supprime les
    formes de nom de la personne que plus aucune source n'atteste.

    Retourne {"detached": N, "deleted_authorships": M, "cleaned_forms": K}.
    """
    publication_ids: set[int] = set()
    for a in authorships:
        if a["source"] in ALL_SOURCES_SET:
            pub_id = repo.find_publication_id_for_source_authorship(a["source"], a["authorship_id"])
            if pub_id is not None:
                publication_ids.add(pub_id)

    detached = 0
    deleted = 0
    for pub_id in publication_ids:
        result = reject_pair(pub_id, person_id, repo=authorship_repo, audit_repo=audit_repo)
        detached += result["detached"]
        deleted += result["deleted_authorships"]

    cleaned_forms = repo.delete_orphan_name_forms_for_person(person_id)

    return {
        "detached": detached,
        "deleted_authorships": deleted,
        "cleaned_forms": cleaned_forms,
    }


# ── Fusion ──


def mark_distinct(
    person_id_a: int,
    person_id_b: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Marque deux personnes comme distinctes (non-doublon) dans
    `distinct_persons`. Idempotent.

    Les IDs sont triés pour garantir l'unicité de la paire.
    """
    inserted = repo.mark_distinct(person_id_a, person_id_b)
    # Audit seulement si une ligne a été insérée (la paire n'existait pas déjà)
    if inserted:
        emit_event(
            audit_repo,
            "person.marked_distinct",
            "person",
            inserted[0],
            {"other_id": inserted[1]},
        )


def merge_person(
    target_id: int,
    source_id: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la personne `source_id` dans `target_id`.

    Orchestration domain-driven : load target + source via le repo,
    délègue l'invariant métier à `Person.can_merge_with` (refus si les
    deux personnes ont chacune une fiche RH distincte), puis applique
    le plumbing FK via `repo.merge_into`.

    Lève `NotFoundError` si target ou source n'existe pas. Lève
    `ConflictError` si l'invariant RH est violé. Émet un événement
    d'audit `person.merged` si un utilisateur est dans le contexte.
    """
    target = repo.find_by_id(target_id)
    source = repo.find_by_id(source_id)
    if target is None:
        raise NotFoundError(f"Personne #{target_id} introuvable")
    if source is None:
        raise NotFoundError(f"Personne #{source_id} introuvable")
    target.can_merge_with(source, has_distinct_rh=repo.has_distinct_rh(target_id, source_id))
    repo.merge_into(target_id, source_id)
    emit_event(audit_repo, "person.merged", "person", target_id, {"source_id": source_id})
