"""Service Personnes — écritures sur l'agrégat Person, transaction-agnostiques.

Couvre les tables `persons`, `person_identifiers` et `person_name_forms`, et le détachement des contributions sources (`source_contributions`). Les appelants sont les command handlers de l'API et l'import RH ; chacun tient sa propre frontière transactionnelle et commite lui-même. Le renommage et l'attribution d'un identifiant passent par le repository des personnes, que la phase `persons` du pipeline utilise aussi.
"""

import logging
from typing import NamedTuple, TypedDict

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import (
    NameFormStatusRow,
    PersonRepository,
)
from application.services._merge import load_merge_pair
from application.services.contributions.core import reject_pair
from domain.errors import NotFoundError, ValidationError
from domain.persons.identifier_attribution import (
    AttributionOutcome,
    held_elsewhere_conflict,
)
from domain.persons.identifiers import (
    PUBLIC_PERSON_IDENTIFIER_TYPES,
    AttributionStatus,
    IdentifierOrigin,
)
from domain.persons.merge import merge_roles
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person import PersonExclusion, validated_name
from domain.sources.registry import require_known_source

logger = logging.getLogger(__name__)


class ContributionRef(TypedDict):
    """Référence d'une contribution source (entrée de `detach_contributions`)."""

    source: str
    source_contribution_id: int


class DetachResult(TypedDict):
    """Résultat de `detach_contributions` : compteurs de l'opération."""

    detached: int
    cleaned_forms: int


# ── Création / mise à jour personne ──


def create_person(last_name: str, first_name: str = "", *, repo: PersonRepository) -> int:
    """Crée une personne et retourne son id.

    Lève `ValidationError` sans patronyme : c'est de lui que `compute_person_name_forms` dérive les formes qui rendent la personne matchable, et une personne qui n'en a pas n'est atteignable par aucun nom.
    """
    last_name, first_name = validated_name(last_name, first_name)
    person_id = repo.create(last_name, first_name)
    repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))
    return person_id


def set_exclusion(
    person_id: int,
    exclusion: PersonExclusion | None,
    *,
    conn: Connection,
    repo: PersonRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Exclut une personne pour le motif `exclusion`, ou la retient si `exclusion` est `None`.

    L'exclusion fait basculer l'appartenance au périmètre de ses publications : le pipeline la recalcule. Lève NotFoundError si la personne n'existe pas.
    """
    repo.set_exclusion(person_id, exclusion)
    perimeter_recompute.refresh_publications_of_person(conn, person_id)
    emit_event(
        audit_repo,
        "person.exclusion",
        "person",
        person_id,
        {"exclusion": exclusion.value if exclusion else None},
    )


def update_name(
    person_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Met à jour le nom/prénom d'une personne et rafraîchit ses formes de nom.

    Le nom est ce par quoi les contributions sources reviennent à une personne : en changer déplace des publications d'une personne à une autre, d'où l'événement d'audit.

    Lève `ValidationError` sans patronyme : le rafraîchissement retirerait alors à la personne les formes de nom que seul son nom canonique porte. Lève `NotFoundError` si la personne n'existe pas.
    """
    last_name, first_name = repo.rename(person_id, last_name, first_name)
    emit_event(
        audit_repo,
        "person.name_updated",
        "person",
        person_id,
        {"last_name": last_name, "first_name": first_name},
    )


# ── Identifiants ──


class AddIdentifierResult(NamedTuple):
    """Retour d'`add_identifier` : l'issue de l'attribution et la valeur normalisée, que l'appelant affiche sans la normaliser de nouveau."""

    outcome: AttributionOutcome
    id_value: str


def _identifiant_ajoute(
    audit_repo: AuditRepository | None,
    person_id: int,
    id_type: str,
    id_value: str,
    outcome: AttributionOutcome,
) -> AddIdentifierResult:
    """Consigne l'attribution d'un identifiant, et rend l'issue à l'appelant."""
    emit_event(
        audit_repo,
        "person_identifier.added",
        "person",
        person_id,
        {"id_type": id_type, "id_value": id_value, "outcome": outcome.value},
    )
    return AddIdentifierResult(outcome, id_value)


def add_identifier(
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    source: IdentifierOrigin = IdentifierOrigin.AUTO,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> AddIdentifierResult:
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

    L'attribution passe par `PersonRepository.attribute_identifier`, qui normalise la valeur et suit `attribution_outcome`. Lève `CannotAttributeConflict` si une autre personne détient l'identifiant en `pending` ou `confirmed`, `ValidationError` sur une valeur malformée.

    `IdentifierOrigin.MANUAL` désigne l'attribution par une utilisatrice, et resserre deux gardes que
    l'appel automatique n'a pas lieu de payer :

    - les types se restreignent à `PUBLIC_PERSON_IDENTIFIER_TYPES` — `hal_person_id` est la
      référence d'un compte HAL, que l'extraction observe dans le TEI, et que personne
      n'attribue à la main ;
    - l'existence de la personne est vérifiée, l'identifiant venant d'un formulaire. La
      promotion depuis les contributions sources (`IdentifierOrigin.AUTO`) en fait l'économie : elle boucle sur
      une personne que la cascade vient de créer ou de rapprocher.
    """
    if source == IdentifierOrigin.MANUAL:
        if id_type not in PUBLIC_PERSON_IDENTIFIER_TYPES:
            raise ValidationError(f"id_type doit être l'un de {PUBLIC_PERSON_IDENTIFIER_TYPES}")
        if repo.find_by_id(person_id) is None:
            raise NotFoundError(f"Personne {person_id} introuvable")
    outcome, id_value, existing = repo.attribute_identifier(
        person_id, id_type, id_value, source=source
    )
    if existing is not None and outcome is AttributionOutcome.HELD_ELSEWHERE:
        raise held_elsewhere_conflict(existing, person_id)
    if outcome is AttributionOutcome.ALREADY_EXISTS:
        # Rien n'a changé : l'appel est idempotent, aucune décision n'a été prise.
        return AddIdentifierResult(outcome, id_value)
    return _identifiant_ajoute(audit_repo, person_id, id_type, id_value, outcome)


class IdentifierStatusResult(NamedTuple):
    """Identifiant après changement de statut, et nombre d'identifiants de ses comptes HAL qui ont reçu le même statut."""

    id: int
    status: str
    person_id: int
    propagated: int


# Statuts qu'une décision sur un identifiant étend aux identifiants de ses comptes HAL.
_PROPAGATED_STATUSES = frozenset(
    {AttributionStatus.CONFIRMED.value, AttributionStatus.REJECTED.value}
)


def update_identifier_status(
    ident_id: int,
    status: str,
    *,
    conn: Connection,
    repo: PersonRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository | None = None,
) -> IdentifierStatusResult:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected).

    Une confirmation ou un rejet s'étend aux identifiants `pending` de la même personne que portent les mêmes comptes HAL (`propagate_status_to_hal_accounts`). Un rejet détache de la personne ses groupes de contributions sources rattachés par ses identifiants rejetés (`detach_groups_of_rejected_identifiers`), puis recalcule l'appartenance au périmètre de leurs publications. Lève NotFoundError si l'identifiant n'existe pas.
    """
    row = repo.update_identifier_status(ident_id, status)
    propagated = (
        repo.propagate_status_to_hal_accounts(ident_id, status)
        if status in _PROPAGATED_STATUSES
        else 0
    )
    if status == AttributionStatus.REJECTED.value:
        publication_ids = repo.detach_groups_of_rejected_identifiers(row["person_id"])
        perimeter_recompute.refresh_publications(conn, publication_ids)
    emit_event(
        audit_repo,
        "person_identifier.status_changed",
        "person",
        row["person_id"],
        {"ident_id": ident_id, "status": status, "propagated": propagated},
    )
    return IdentifierStatusResult(row["id"], row["status"], row["person_id"], propagated)


# ── Formes de noms ──


def refresh_person_name_forms(
    person_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: PersonRepository,
) -> None:
    """Recalcule les formes de nom de source 'persons' d'une personne : calcul via le domaine, écriture par le repository."""
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
    conn: Connection,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository | None = None,
) -> NameFormStatusRow:
    """Met à jour le statut d'une forme de nom (pending/confirmed/rejected).

    `confirmed` valide le lien. `rejected` est le verrou de non-retour ET déclenche le **détachement** des contributions sources sous cette forme : leur `person_id` passe à NULL. Les contributions sources que l'admin a épinglées sur la personne restent rattachées, épinglage compris. Les groupes de la personne rattachés par le nom dont un membre porte la forme perdent la personne (`detach_groups_for_name_form`), et l'appartenance au périmètre de leurs publications est recalculée.

    Retourne la ligne {person_id, name_form, status}. Lève NotFoundError si le couple (name_form, person_id) n'existe pas, et ConflictError si la forme dérive du nom de la personne, confirmée d'office.
    """
    row = repo.update_name_form_status(person_id, name_form, status)
    if status == "rejected":
        contribution_repo.null_person_id_for_name_form(person_id, name_form)
        publication_ids = contribution_repo.detach_groups_for_name_form(person_id, name_form)
        perimeter_recompute.refresh_publications(conn, publication_ids)
    emit_event(
        audit_repo,
        "person_name_form.status_changed",
        "person",
        person_id,
        {"name_form": name_form, "status": status},
    )
    return row


def detach_contributions(
    person_id: int,
    contributions: list[ContributionRef],
    *,
    conn: Connection,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository | None = None,
) -> DetachResult:
    """Rejette durablement les paires (publication, personne) couvertes par un lot de contributions sources sélectionnées.

    Le rejet porte sur la publication entière : on résout l'ensemble distinct des `publication_id` des sources sélectionnées et on applique `reject_pair` à chaque paire (enregistrement du rejet, détachement du groupe et de toutes les sources de la paire). Puis on supprime les formes de nom de la personne qu'aucune source restante n'atteste.

    Retourne {"detached": N, "cleaned_forms": K}.
    """
    publication_ids: set[int] = set()
    for a in contributions:
        require_known_source(a["source"])
        publication_id = contribution_repo.find_publication_id_for_source_contribution(
            a["source_contribution_id"]
        )
        if publication_id is not None:
            publication_ids.add(publication_id)

    detached = 0
    for publication_id in publication_ids:
        result = reject_pair(
            publication_id,
            person_id,
            conn=conn,
            repo=contribution_repo,
            perimeter_recompute=perimeter_recompute,
            audit_repo=audit_repo,
        )
        detached += result["detached"]

    cleaned_forms = repo.delete_orphan_name_forms_for_person(person_id)

    return {
        "detached": detached,
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
    """Marque deux personnes comme distinctes (non-doublon) dans `distinct_persons`. Idempotent : l'événement d'audit n'est émis que si la paire vient d'être insérée.

    Lève `ValidationError` sur deux identifiants égaux : une personne n'est pas un non-doublon d'elle-même.
    """
    if person_id_a == person_id_b:
        raise ValidationError("Impossible de distinguer une personne d'elle-même")
    inserted = repo.mark_distinct(person_id_a, person_id_b)
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
) -> tuple[int, int]:
    """Fusionne les personnes `target_id` et `source_id`, et retourne (id conservé, id absorbé).

    Les rôles demandés sont inversés si seule `source_id` a une fiche RH (`merge_roles`). Le repo reprend ensuite les clés étrangères (`repo.merge_into`).

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` si target ou source n'existe pas, `ConflictError` si les deux ont une fiche RH. Émet un événement d'audit `person.merged` si un utilisateur est dans le contexte.
    """
    load_merge_pair(target_id, source_id, repo.find_by_id, label="Personne")
    target_id, source_id = merge_roles(
        target_id, source_id, with_rh=repo.ids_with_rh([target_id, source_id])
    )
    repo.merge_into(target_id, source_id)
    emit_event(audit_repo, "person.merged", "person", target_id, {"source_id": source_id})
    return target_id, source_id
