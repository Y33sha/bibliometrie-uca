"""Exceptions métier du domaine bibliométrique.

Ces exceptions sont levées par la couche services/ pour signaler des
situations métier sans dépendre de FastAPI. La traduction en codes HTTP
se fait dans backend/app.py via des exception handlers dédiés.
"""

from typing import TypedDict


class DomainError(Exception):
    """Classe de base pour toutes les erreurs métier."""


class NotFoundError(DomainError):
    """Ressource demandée introuvable (→ HTTP 404)."""


class ValidationError(DomainError):
    """Entrée invalide : champ manquant, format incorrect, valeur hors domaine (→ HTTP 400)."""


class ConflictError(DomainError):
    """Opération refusée car elle violerait un invariant métier :
    fusion d'une entité avec elle-même, suppression d'une ressource référencée,
    création d'un doublon interdit, etc. (→ HTTP 409)."""


class CannotAttributeConflict(ConflictError):
    """Tentative d'attribution d'un identifiant déjà attribué à une autre
    personne avec un statut `pending` ou `confirmed`. Pour réattribuer,
    le statut existant doit d'abord être passé à `rejected`.

    Porte, quand ils sont disponibles, les champs structurés du conflit (type et
    valeur de l'identifiant, personne détentrice et son statut) : le path batch de la
    cascade personnes les collecte pour arbitrer un transfert par consensus au lieu de
    refuser en bloc. Le chemin admin unitaire les ignore (refus strict → 409)."""

    def __init__(
        self,
        message: str,
        *,
        id_type: str | None = None,
        id_value: str | None = None,
        existing_person_id: int | None = None,
        existing_status: str | None = None,
    ) -> None:
        self.id_type = id_type
        self.id_value = id_value
        self.existing_person_id = existing_person_id
        self.existing_status = existing_status
        super().__init__(message)


class BlockingJournal(TypedDict):
    """Description structurée d'une paire de journaux qui bloque la fusion
    de deux éditeurs (cf. `PublisherMergeBlockedError`)."""

    target_journal_id: int
    target_title: str
    source_journal_id: int
    source_title: str
    reason: str  # explication lisible (ex: "ISSN différents : 0028-0836 vs 9999-9999")


class PublisherMergeBlockedError(ConflictError):
    """Fusion d'éditeurs refusée parce que des paires de revues ne peuvent
    pas être fusionnées automatiquement (ex: ISSN divergents pour des
    revues partageant le même titre). L'utilisatrice doit traiter les
    paires bloquantes côté admin Revues d'abord, puis relancer la fusion.

    `blocking_journals` énumère les paires problématiques pour que l'UI
    puisse les afficher et permettre l'action manuelle."""

    def __init__(self, blocking_journals: list[BlockingJournal]) -> None:
        self.blocking_journals = blocking_journals
        n = len(blocking_journals)
        super().__init__(
            f"Fusion bloquée par {n} paire{'s' if n > 1 else ''} de revues à traiter manuellement"
        )


class DistinctDoiError(ConflictError):
    """Fusion refusée : deux publications portent des DOI non-nuls différents.

    Par principe « 1 DOI = 1 publication », elles désignent des œuvres
    distinctes et ne peuvent pas fusionner — quelle que soit la clé qui les a
    rapprochées (hal_id, nnt, pmid, métadonnées). Les cas où l'on voudrait
    malgré tout fusionner (DOI erroné, ou documents liés) sont traités à part."""

    def __init__(self, target_id: int, source_id: int, target_doi: str, source_doi: str) -> None:
        self.target_id = target_id
        self.source_id = source_id
        self.target_doi = target_doi
        self.source_doi = source_doi
        super().__init__(
            f"Fusion refusée : #{target_id} ({target_doi}) et "
            f"#{source_id} ({source_doi}) ont des DOI distincts"
        )


class UnauthorizedError(DomainError):
    """Accès refusé : session invalide ou permissions insuffisantes (→ HTTP 401)."""


class RejectedPair(TypedDict):
    """Paire (publication, personne) figurant dans le registre des rejets,
    qui bloque une réassignation (cf. `RejectedPairError`)."""

    publication_id: int
    person_id: int
    rejected_at: str  # ISO 8601


class RejectedPairError(ConflictError):
    """Réassignation refusée : une ou plusieurs paires (publication, personne)
    ont déjà été rejetées et figurent dans `rejected_authorships`. Réassigner
    recréerait un lien explicitement rejeté ; l'utilisatrice doit confirmer
    pour lever le rejet (`force=true`).

    `rejected_pairs` énumère les paires concernées (avec la date du rejet) pour
    que l'UI les affiche avant de demander confirmation."""

    def __init__(self, rejected_pairs: list[RejectedPair]) -> None:
        self.rejected_pairs = rejected_pairs
        n = len(rejected_pairs)
        super().__init__(
            f"{n} paire{'s' if n > 1 else ''} (publication, personne) "
            f"déjà rejetée{'s' if n > 1 else ''}"
        )
