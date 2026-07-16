"""Service Personnes — écritures sur l'agrégat Person, transaction-agnostiques.

Couvre les tables `persons`, `person_identifiers` et `person_name_forms`, plus le rattachement des authorships sources (`source_authorships`), dont le `person_id` porte le lien vers la personne. Les appelants sont la phase `persons` du pipeline, les command handlers de l'API et les CLI de maintenance ; chacun tient sa propre frontière transactionnelle et commite lui-même.

Toute écriture éditoriale passe par ce service, pipeline compris (`create_person` dans la cascade). Les formes de nom dérivées, que la phase `persons` resynchronise sur tout le stock, s'écrivent en SQL ensembliste (`infrastructure/queries/pipeline/person_name_forms.py`), hors de ce service qui traite une personne à la fois.
"""

import logging
from collections import Counter
from enum import StrEnum
from typing import NamedTuple, TypedDict

from application.audit_log import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import (
    AuthenticateOrcidOutcome,
    IdentifierStatusRow,
    NameFormStatusRow,
    PersonRepository,
)
from application.services.authorships.core import reject_pair
from domain.errors import CannotAttributeConflict, NotFoundError, ValidationError
from domain.persons.identifiers import (
    PERSON_IDENTIFIER_TYPES,
    AttributionStatus,
    normalized_identifier_value,
)
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person_identifier import PersonIdentifier
from domain.sources.registry import require_known_source
from domain.types import JsonValue

logger = logging.getLogger(__name__)


class AuthorshipRef(TypedDict):
    """Référence d'une signature source (entrée de `detach_authorships`)."""

    source: str
    authorship_id: int


class DetachResult(TypedDict):
    """Résultat de `detach_authorships` : compteurs de l'opération."""

    detached: int
    deleted_authorships: int
    cleaned_forms: int


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
    resolution_mode: str,
) -> None:
    """Rattache une authorship source à une personne (pipeline), en marquant le canal. Lève `ValidationError` sur une source hors registre."""
    require_known_source(source)
    repo.link_authorship(person_id, source, authorship_id, resolution_mode)


def unlink_authorship(
    person_id: int, source: str, authorship_id: int, *, repo: PersonRepository
) -> None:
    """Détache une authorship source d'une personne (met person_id à NULL). Lève `ValidationError` sur une source hors registre."""
    require_known_source(source)
    repo.unlink_authorship(person_id, source, authorship_id)


# ── Identifiants ──


class AddIdentifierOutcome(StrEnum):
    """Issue de la cascade de décision d'`add_identifier`.

    L'appelant (API) traduit l'issue en réponse ; un conflit lève `CannotAttributeConflict` (hors énumération).
    """

    ADDED = "added"  # insertion en `pending`
    ALREADY_EXISTS = "already_exists"  # déjà porté par cette personne (no-op)
    REASSIGNED = "reassigned"  # repris d'une autre personne (était `rejected`)


class AddIdentifierResult(NamedTuple):
    """Retour d'`add_identifier` : l'issue de la cascade et la valeur canonique normalisée, que l'appelant ré-affiche sans re-normaliser."""

    outcome: AddIdentifierOutcome
    id_value: str


def add_identifier(
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    source: str = "auto",
    repo: PersonRepository,
) -> AddIdentifierResult:
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

    Charge l'éventuel `PersonIdentifier` existant pour `(id_type, id_value)`
    et dispatche, en renvoyant l'issue (`AddIdentifierResult`) :

    - **absent** → insertion en `pending` (`ADDED`)
    - **existant sur cette personne** → idempotent, no-op (`ALREADY_EXISTS`)
    - **existant sur autre personne en `rejected`** → réattribution
      (statut → `pending`, via `PersonIdentifier.reattribute_to` ; `REASSIGNED`)
    - **existant sur autre personne en `pending` ou `confirmed`** →
      lève `CannotAttributeConflict`. Pour réattribuer, le statut
      existant doit d'abord être passé à `rejected` (via
      `update_identifier_status` ou `reassign_identifier`).

    La valeur est validée et normalisée via le value object du type
    (`normalized_identifier_value`) avant lookup et écriture, de sorte que la même
    forme canonique sert aux deux et soit renvoyée dans le résultat. Lève
    `ValidationError` si elle est malformée.
    """
    id_value = normalized_identifier_value(id_type, id_value)
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
        return AddIdentifierResult(AddIdentifierOutcome.ADDED, id_value)

    if existing.person_id == person_id:
        return AddIdentifierResult(AddIdentifierOutcome.ALREADY_EXISTS, id_value)

    if existing.status is AttributionStatus.REJECTED:
        existing.reattribute_to(person_id, source=source)
        repo.update_identifier(existing)
        return AddIdentifierResult(AddIdentifierOutcome.REASSIGNED, id_value)

    raise CannotAttributeConflict(
        f"Identifiant {id_type}={id_value!r} déjà attribué à person_id={existing.person_id} "
        f"avec statut {existing.status.value!r} ; impossible d'attribuer à person_id={person_id}.",
        id_type=id_type,
        id_value=id_value,
        existing_person_id=existing.person_id,
        existing_status=existing.status.value,
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
) -> IdentifierStatusRow:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected).

    Retourne la ligne {id, status, person_id} mise à jour.
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
    return row


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


def authenticate_orcids(
    entries: list[tuple[int, str]], *, repo: PersonRepository
) -> Counter[AuthenticateOrcidOutcome]:
    """Applique le statut `authenticated` à des paires `(person_id, orcid)` déjà résolues, et retourne le décompte des issues.

    Ouvre une fois le contexte d'écriture protégé pour la transaction courante (`begin_authenticated_orcid_import`), puis délègue chaque paire à `authenticate_orcid`. Les valeurs ORCID sont supposées déjà normalisées et les personnes déjà résolues : l'appelant qui lit le fichier des ORCID authentifiés porte cette préparation.

    Unique chemin d'écriture autorisé pour ce statut : ailleurs, le trigger `protect_authenticated_identifier` rejette toute écriture de `authenticated`.
    """
    repo.begin_authenticated_orcid_import()
    return Counter(repo.authenticate_orcid(person_id, orcid) for person_id, orcid in entries)


class IdentifierConflict(NamedTuple):
    """Conflit d'attribution collecté par le traitement par lot : une valeur d'identifiant portée par une signature du candidat est déjà attribuée à un autre propriétaire.

    Arbitré après la cascade par le consensus des porteurs (canal identifiant ordre-indépendant) : la valeur est transférée au candidat si le consensus le désigne face au propriétaire. `owner_status` distingue le `pending` (transférable) du `confirmed` (verrou admin, jamais transféré)."""

    id_type: str
    id_value: str
    candidate_person_id: int
    owner_person_id: int
    owner_status: str


def add_identifiers_from_authorships(
    person_id: int,
    authorships: list[dict[str, JsonValue]],
    *,
    repo: PersonRepository,
) -> None:
    """Promotion canonique en batch : pour chaque authorship source, extrait les identifiants observés (orcid/idhal/idref/hal_person_id) et délègue à `add_identifier` qui dispatche selon l'état existant en base.

    Traitement par lot tolérant : un `ValidationError` (identifiant source mal formé) est loggé et la promotion continue. Un `CannotAttributeConflict` (valeur déjà attribuée en pending/confirmed à une autre personne) est loggé en warning et la valeur n'est pas écrasée — l'arbitrage par consensus du balayage frontal de la phase (`detect_identifier_conflicts`) le tranche au run suivant. Le point d'entrée strict reste `add_identifier` (singulier), que l'API admin utilise directement.

    Balaie les types d'identifiants acceptés en base (`PERSON_IDENTIFIER_TYPES`) ; la lecture filtre ensuite ceux réservés à l'usage interne (`PUBLIC_PERSON_IDENTIFIER_TYPES`). La valeur est convertie en `str` pour la table `person_identifiers`, `hal_person_id` arrivant en `int` depuis la query (cf. `fetch_unlinked_authorships`). La `source` enregistrée garde sa valeur par défaut (`'auto'`).
    """
    seen: set[tuple[str, str]] = set()
    for a in authorships:
        for id_type in PERSON_IDENTIFIER_TYPES:
            raw = a.get(id_type)
            if not raw:
                continue
            # Cible `person_identifiers` = text ; `hal_person_id` arrive en int,
            # les autres en str — `str()` couvre les deux.
            value = str(raw)
            if (id_type, value) in seen:
                continue
            seen.add((id_type, value))
            try:
                add_identifier(person_id, id_type, value, repo=repo)
            except CannotAttributeConflict as exc:
                # Valeur déjà prise par une autre personne : on n'écrase pas. Le conflit est
                # tranché par le balayage frontal de la phase (arbitrage par consensus) au run
                # suivant — inutile de le collecter ici.
                logger.warning("%s", exc)
            except ValidationError:
                logger.warning("Identifiant mal formé ignoré : %s=%r", id_type, value)


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
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository | None = None,
    audit_repo: AuditRepository | None = None,
) -> NameFormStatusRow:
    """Met à jour le statut d'une forme de nom (pending/confirmed/rejected).

    `confirmed` valide le lien. `rejected` est le verrou de non-retour ET déclenche le **détachement** des signatures portant cette forme : leurs `source_authorships` sont nullées et les `authorships` canoniques devenues sans source sont supprimées.

    Retourne la ligne {person_id, name_form, status}. Lève NotFoundError si le couple (name_form, person_id) n'existe pas.
    """
    row = repo.update_name_form_status(person_id, name_form, status)
    if status == "rejected":
        detached = repo.null_person_id_for_name_form(person_id, name_form)
        if authorship_repo is not None:
            # Le rejet de forme détache : retirer aussi l'épinglage éventuel des
            # signatures concernées, sinon le pipeline les réattacherait.
            authorship_repo.unpin_authorships_for_name_form(person_id, name_form)
            if detached:
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
    authorships: list[AuthorshipRef],
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository | None = None,
) -> DetachResult:
    """Rejette durablement les paires (publication, personne) couvertes par un lot d'authorships sources sélectionnées.

    Le rejet porte sur la publication entière : on résout l'ensemble distinct des `publication_id` des sources sélectionnées et on applique `reject_pair` à chaque paire (enregistrement du rejet, détachement de toutes les sources de la paire, suppression de la ligne consolidée). Puis on supprime les formes de nom de la personne qu'aucune source restante n'atteste.

    Retourne {"detached": N, "deleted_authorships": M, "cleaned_forms": K}.
    """
    publication_ids: set[int] = set()
    for a in authorships:
        require_known_source(a["source"])
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
    """Marque deux personnes comme distinctes (non-doublon) dans `distinct_persons`. Idempotent : l'événement d'audit n'est émis que si la paire vient d'être insérée."""
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
) -> None:
    """Fusionne la personne `source_id` dans `target_id`.

    Charge target et source via le repo, délègue l'invariant métier à `Person.can_merge_with` (refus si les deux personnes ont chacune une fiche RH distincte), puis reprend les clés étrangères via `repo.merge_into`.

    Lève `NotFoundError` si target ou source n'existe pas. Lève `ConflictError` si l'invariant RH est violé. Émet un événement d'audit `person.merged` si un utilisateur est dans le contexte.
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
