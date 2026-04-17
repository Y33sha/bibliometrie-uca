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


class UnauthorizedError(DomainError):
    """Accès refusé : session invalide ou permissions insuffisantes (→ HTTP 401)."""
