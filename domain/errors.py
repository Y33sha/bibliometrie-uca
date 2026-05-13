"""Exceptions métier du domaine bibliométrique.

Ces exceptions sont levées par la couche services/ pour signaler des
situations métier sans dépendre de FastAPI. La traduction en codes HTTP
se fait dans backend/app.py via des exception handlers dédiés.
"""


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


class CannotReattributeError(ConflictError):
    """Tentative de réattribution d'un `PersonIdentifier` depuis un statut
    autre que `rejected`. Levée par `PersonIdentifier.reattribute_to`."""


class CannotAttributeConflict(ConflictError):
    """Tentative d'attribution d'un identifiant déjà attribué à une autre
    personne avec un statut `pending` ou `confirmed`. Pour réattribuer,
    le statut existant doit d'abord être passé à `rejected`."""


class UnauthorizedError(DomainError):
    """Accès refusé : session invalide ou permissions insuffisantes (→ HTTP 401)."""
