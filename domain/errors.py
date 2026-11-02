"""Exceptions métier. `interfaces/api/app.py` les traduit en codes HTTP."""

from typing import TypedDict


class DomainError(Exception):
    """Classe de base des erreurs métier."""


class NotFoundError(DomainError):
    """Ressource demandée introuvable."""


class ValidationError(DomainError):
    """Entrée invalide."""


class ConflictError(DomainError):
    """Opération refusée : elle violerait un invariant métier."""


class BlockingSerial(TypedDict):
    """Paire de revues qui bloque la fusion de deux éditeurs."""

    target_serial_id: int
    target_title: str
    source_serial_id: int
    source_title: str
    reason: str
    """Explication lisible : « ISSN différents : 0028-0836 vs 9999-9999 »."""


class PublisherMergeBlockedError(ConflictError):
    """Fusion d'éditeurs refusée : des paires de revues de même titre ne se fusionnent pas automatiquement, par exemple pour des ISSN divergents."""

    def __init__(self, blocking_serials: list[BlockingSerial]) -> None:
        self.blocking_serials = blocking_serials
        n = len(blocking_serials)
        super().__init__(
            f"Fusion bloquée par {n} paire{'s' if n > 1 else ''} de revues à traiter manuellement"
        )


class RejectedPair(TypedDict):
    """Paire (publication, personne) rejetée, qui bloque une réattribution."""

    publication_id: int
    person_id: int
    rejected_at: str  # ISO 8601


class RejectedPairError(ConflictError):
    """Réattribution refusée : des paires (publication, personne) sont rejetées. Une réattribution forcée retire le rejet."""

    def __init__(self, rejected_pairs: list[RejectedPair]) -> None:
        self.rejected_pairs = rejected_pairs
        n = len(rejected_pairs)
        super().__init__(
            f"{n} paire{'s' if n > 1 else ''} (publication, personne) "
            f"déjà rejetée{'s' if n > 1 else ''}"
        )
