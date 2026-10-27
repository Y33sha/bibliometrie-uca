"""Service Personnes — écritures sur l'agrégat Person.

Couvre les tables `persons`, `person_identifiers` et `person_name_forms`, et le détachement des contributions (`contributions`). Le renommage et l'attribution d'un identifiant passent par le repository des personnes, que la phase `persons` du pipeline utilise aussi.
"""

from typing import NamedTuple, TypedDict

from application.audit_log import emit_event
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import (
    NameFormStatusRow,
    PersonRepository,
)
from application.services._merge import check_merge_pair
from application.services.contributions import reject_pair
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
from domain.persons.person import PersonExclusion
from domain.sources.registry import require_known_source


class ContributionRef(TypedDict):
    """Référence d'une contribution source (entrée de `detach_contributions`)."""

    source: str
    source_contribution_id: int


class DetachResult(TypedDict):
    """Résultat de `detach_contributions` : contributions détachées et formes de nom supprimées."""

    detached: int
    cleaned_forms: int


class AddIdentifierResult(NamedTuple):
    """Retour d'`add_identifier` : l'issue de l'attribution et la valeur normalisée, que l'appelant affiche sans la normaliser de nouveau."""

    outcome: AttributionOutcome
    id_value: str


class IdentifierStatusResult(NamedTuple):
    """Identifiant après changement de statut, et nombre d'identifiants de ses comptes HAL qui ont reçu le même statut."""

    id: int
    status: str
    person_id: int
    propagated: int


# Statuts qu'une décision sur un identifiant étend aux identifiants de ses comptes HAL.
_PROPAGATED_STATUSES = frozenset({AttributionStatus.CONFIRMED, AttributionStatus.REJECTED})


class PersonService:
    """Écritures sur les personnes, leurs identifiants, leurs formes de nom et leurs contributions."""

    def __init__(
        self,
        *,
        persons: PersonRepository,
        contributions: ContributionRepository,
        perimeter_recompute: PublicationPerimeterRecompute,
    ) -> None:
        self._persons = persons
        self._contributions = contributions
        self._perimeter_recompute = perimeter_recompute

    # ── Exclusion et renommage ──

    def set_exclusion(self, person_id: int, exclusion: PersonExclusion | None) -> None:
        """Exclut une personne pour le motif `exclusion`, ou la retient si `exclusion` est `None`.

        L'exclusion fait basculer l'appartenance au périmètre de ses publications : le pipeline la recalcule. Lève NotFoundError si la personne n'existe pas.
        """
        self._persons.set_exclusion(person_id, exclusion)
        self._perimeter_recompute.refresh_publications_of_person(person_id)
        emit_event(
            "person.exclusion",
            "person",
            person_id,
            {"exclusion": exclusion.value if exclusion else None},
        )

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        """Met à jour le nom/prénom d'une personne et rafraîchit ses formes de nom.

        Le nom est ce par quoi les contributions sources reviennent à une personne : en changer déplace des publications d'une personne à une autre, d'où l'événement d'audit.

        Lève `ValidationError` sans patronyme : le rafraîchissement retirerait alors à la personne les formes de nom qui dérivent de son seul nom. Lève `NotFoundError` si la personne n'existe pas.
        """
        last_name, first_name = self._persons.rename(person_id, last_name, first_name)
        emit_event(
            "person.name_updated",
            "person",
            person_id,
            {"last_name": last_name, "first_name": first_name},
        )

    # ── Identifiants ──

    def add_identifier(self, person_id: int, id_type: str, id_value: str) -> AddIdentifierResult:
        """Attribue à la main un identifiant (ORCID, idHAL, IdRef) à une personne.

        L'attribution passe par `PersonRepository.attribute_identifier`, qui normalise la valeur et suit `attribution_outcome`. Le type se restreint à `PUBLIC_PERSON_IDENTIFIER_TYPES` : `hal_person_id` est la référence d'un compte HAL, que l'extraction observe dans le TEI.

        Lève `ValidationError` sur un type hors de cette liste ou une valeur malformée, `NotFoundError` sur une personne absente, `CannotAttributeConflict` si une autre personne détient l'identifiant en `pending` ou `confirmed`.
        """
        if id_type not in PUBLIC_PERSON_IDENTIFIER_TYPES:
            raise ValidationError(f"id_type doit être l'un de {PUBLIC_PERSON_IDENTIFIER_TYPES}")
        if self._persons.find_by_id(person_id) is None:
            raise NotFoundError(f"Personne {person_id} introuvable")
        outcome, id_value, existing = self._persons.attribute_identifier(
            person_id, id_type, id_value, source=IdentifierOrigin.MANUAL
        )
        if existing is not None and outcome is AttributionOutcome.HELD_ELSEWHERE:
            raise held_elsewhere_conflict(existing, person_id)
        if outcome is not AttributionOutcome.ALREADY_EXISTS:
            # Un appel répété ne change rien : seule une attribution effective est consignée.
            emit_event(
                "person_identifier.added",
                "person",
                person_id,
                {"id_type": id_type, "id_value": id_value, "outcome": outcome.value},
            )
        return AddIdentifierResult(outcome, id_value)

    def update_identifier_status(
        self, ident_id: int, status: AttributionStatus
    ) -> IdentifierStatusResult:
        """Met à jour le statut d'un identifiant (pending/confirmed/rejected).

        Une confirmation ou un rejet s'étend aux identifiants `pending` de la même personne que contiennent les mêmes comptes HAL (`propagate_status_to_hal_accounts`). Un rejet marque pour la redécision de leur personne les contributions que ses identifiants rejetés lui rattachent (`mark_contributions_of_rejected_identifiers`) : le run suivant les redécide. Lève NotFoundError si l'identifiant n'existe pas.
        """
        row = self._persons.update_identifier_status(ident_id, status)
        propagated = (
            self._persons.propagate_status_to_hal_accounts(ident_id, status)
            if status in _PROPAGATED_STATUSES
            else 0
        )
        if status == AttributionStatus.REJECTED:
            self._persons.mark_contributions_of_rejected_identifiers(row["person_id"])
        emit_event(
            "person_identifier.status_changed",
            "person",
            row["person_id"],
            {"ident_id": ident_id, "status": status, "propagated": propagated},
        )
        return IdentifierStatusResult(row["id"], row["status"], row["person_id"], propagated)

    # ── Formes de noms ──

    def update_name_form_status(
        self, person_id: int, name_form: str, status: AttributionStatus
    ) -> NameFormStatusRow:
        """Met à jour le statut d'une forme de nom (pending/confirmed/rejected).

        `confirmed` valide le lien. `rejected` est le verrou de non-retour. Il marque aussi pour la redécision de leur personne les contributions de la personne rattachées par le nom dont une contribution source contient la forme (`mark_contributions_for_name_form`) : le run suivant les redécide. Les contributions épinglées restent en l'état.

        Retourne la ligne {person_id, name_form, status}. Lève NotFoundError si le couple (name_form, person_id) n'existe pas, et ConflictError si la forme dérive du nom de la personne, confirmée d'office.
        """
        row = self._persons.update_name_form_status(person_id, name_form, status)
        if status == AttributionStatus.REJECTED:
            self._contributions.mark_contributions_for_name_form(person_id, name_form)
        emit_event(
            "person_name_form.status_changed",
            "person",
            person_id,
            {"name_form": name_form, "status": status},
        )
        return row

    def detach_contributions(
        self, person_id: int, contributions: list[ContributionRef]
    ) -> DetachResult:
        """Rejette durablement les paires (publication, personne) couvertes par un lot de contributions sources sélectionnées.

        Le rejet porte sur la publication entière : on résout l'ensemble distinct des `publication_id` des sources sélectionnées et on applique `reject_pair` à chaque paire (enregistrement du rejet, détachement de la contribution de la personne). Puis on supprime les formes de nom de la personne qu'aucune source restante n'atteste.

        Retourne {"detached": N, "cleaned_forms": K}, N contributions détachées.
        """
        publication_ids: set[int] = set()
        for a in contributions:
            require_known_source(a["source"])
            publication_id = self._contributions.find_publication_id_for_source_contribution(
                a["source_contribution_id"]
            )
            if publication_id is not None:
                publication_ids.add(publication_id)

        detached = 0
        for publication_id in publication_ids:
            detached += reject_pair(
                publication_id,
                person_id,
                repo=self._contributions,
                perimeter_recompute=self._perimeter_recompute,
            )

        cleaned_forms = self._persons.delete_orphan_name_forms_for_person(person_id)

        return {
            "detached": detached,
            "cleaned_forms": cleaned_forms,
        }

    # ── Fusion ──

    def mark_distinct(self, person_id_a: int, person_id_b: int) -> None:
        """Marque deux personnes comme distinctes (non-doublon) dans `distinct_persons`. Idempotent : l'événement d'audit n'est émis que si la paire vient d'être insérée.

        Lève `ValidationError` sur deux identifiants égaux : une personne n'est pas un non-doublon d'elle-même.
        """
        if person_id_a == person_id_b:
            raise ValidationError("Impossible de distinguer une personne d'elle-même")
        inserted = self._persons.mark_distinct(person_id_a, person_id_b)
        if inserted:
            emit_event(
                "person.marked_distinct",
                "person",
                inserted[0],
                {"other_id": inserted[1]},
            )

    def unmark_distinct(self, person_id_a: int, person_id_b: int) -> None:
        """Annule la décision qui déclare deux personnes distinctes. Idempotent : l'événement d'audit est émis seulement si la paire existait."""
        removed = self._persons.unmark_distinct(person_id_a, person_id_b)
        if removed:
            emit_event(
                "person.unmarked_distinct",
                "person",
                removed[0],
                {"other_id": removed[1]},
            )

    def merge_person(self, target_id: int, source_id: int) -> tuple[int, int]:
        """Fusionne les personnes `target_id` et `source_id`, et retourne (id conservé, id absorbé).

        Les rôles demandés sont inversés si seule `source_id` a une fiche RH (`merge_roles`). Le repository reprend ensuite les clés étrangères (`PersonRepository.merge_into`).

        Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` si target ou source n'existe pas, `ConflictError` si les deux ont une fiche RH. Émet un événement d'audit `person.merged` si un utilisateur est dans le contexte.
        """
        check_merge_pair(target_id, source_id, self._persons.find_by_id, label="Personne")
        target_id, source_id = merge_roles(
            target_id, source_id, with_rh=self._persons.ids_with_rh([target_id, source_id])
        )
        self._persons.merge_into(target_id, source_id)
        emit_event("person.merged", "person", target_id, {"source_id": source_id})
        return target_id, source_id
