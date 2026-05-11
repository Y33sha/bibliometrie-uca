"""
Service Référentiel Personnes — accès exclusif en écriture aux tables
`persons`, `person_identifiers`, `person_name_forms`.

Gère aussi le rattachement/détachement des authorships sources
(source_authorships) puisque le person_id y est la source de vérité
du lien personne.

Les auteurs sources sont dans la table unifiée `source_persons`
(UNIQUE(source, source_id)), les authorships utilisent `source_person_id`.
"""

from application.audit import emit_event
from application.authorships.core import delete_orphan_authorships
from domain.names import compute_person_name_forms
from domain.persons.merge import check_can_merge_persons
from domain.ports.audit_repository import AuditRepository
from domain.ports.authorship_repository import AuthorshipRepository
from domain.ports.person_repository import PersonRepository
from domain.sources import ALL_SOURCES_SET

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
    "detach_name_form",
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


def link_authorships(person_id: int, authorships: list[dict], *, repo: PersonRepository) -> None:
    """Rattache un groupe d'authorships à une personne (pipeline).

    Chaque dict doit avoir 'source' et 'authorship_id',
    et optionnellement 'source_person_id' et 'has_hal_person_id'.
    """
    for a in authorships:
        link_authorship(
            person_id,
            a["source"],
            a["authorship_id"],
            source_person_id=a.get("source_person_id"),
            has_hal_person_id=a.get("has_hal_person_id", False),
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
                add_identifier(person_id, id_type, value, repo=repo)
                seen.add((id_type, value))


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


def detach_name_form(person_id: int, name_form: str, *, repo: PersonRepository) -> None:
    """Détache une personne d'une forme de nom. Supprime la forme si
    person_ids devient vide."""
    repo.detach_name_form(person_id, name_form)


def detach_authorships(
    person_id: int,
    authorships: list[dict],
    name_form: str | None = None,
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
) -> dict:
    """Détache un lot d'authorships sources d'une personne et nettoie les
    authorships vérité devenues orphelines.

    Si `name_form` est fourni, supprime aussi la forme de nom de la personne
    lorsque plus aucune authorship ne la porte.

    Retourne {"detached": N, "deleted_authorships": M, "cleaned_form": bool}.
    """
    for a in authorships:
        if a["source"] in ALL_SOURCES_SET:
            repo.unlink_authorship(person_id, a["source"], a["authorship_id"])

    deleted = delete_orphan_authorships(person_id, repo=authorship_repo)

    cleaned_form = False
    if name_form and repo.count_authorships_with_name_form(person_id, name_form) == 0:
        repo.detach_name_form(person_id, name_form)
        cleaned_form = True

    return {
        "detached": len(authorships),
        "deleted_authorships": deleted,
        "cleaned_form": cleaned_form,
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

    Invariant métier : refus si les deux personnes ont chacune une
    fiche RH distincte (risque de perdre de l'information humaine).

    Lève ConflictError si l'invariant est violé. Émet un événement
    d'audit `person.merged` si l'utilisateur est dans le contexte.
    """
    check_can_merge_persons(repo.has_distinct_rh(target_id, source_id), target_id, source_id)
    repo.merge_into(target_id, source_id)
    emit_event(audit_repo, "person.merged", "person", target_id, {"source_id": source_id})
