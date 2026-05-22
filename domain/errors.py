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
    le statut existant doit d'abord être passé à `rejected`."""


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


class UnauthorizedError(DomainError):
    """Accès refusé : session invalide ou permissions insuffisantes (→ HTTP 401)."""
