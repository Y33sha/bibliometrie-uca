"""Exceptions métier. `interfaces/api/app.py` les traduit en codes HTTP."""

from typing import TypedDict


class DomainError(Exception):
    """Classe de base des erreurs métier."""


class NotFoundError(DomainError):
    """Ressource demandée introuvable."""


class ValidationError(DomainError):
    """Entrée invalide."""


class ConflictError(DomainError):
    """Opération refusée, car elle violerait un invariant métier."""


class IdentifierAttributionConflictError(ConflictError):
    """Attribution d'un identifiant refusée par le statut de son attribution existante."""

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


class BlockingSerial(TypedDict):
    """Paire de revues qui bloque la fusion de deux éditeurs."""

    target_serial_id: int
    target_title: str
    source_serial_id: int
    source_title: str
    reason: str  # explication lisible, p. ex. « ISSN différents : 0028-0836 vs 9999-9999 »


class PublisherMergeBlockedError(ConflictError):
    """Fusion d'éditeurs refusée : des paires de revues de même titre ne se fusionnent pas automatiquement, par exemple pour des ISSN divergents."""

    def __init__(self, blocking_serials: list[BlockingSerial]) -> None:
        self.blocking_serials = blocking_serials
        n = len(blocking_serials)
        super().__init__(
            f"Fusion bloquée par {n} paire{'s' if n > 1 else ''} de revues à traiter manuellement"
        )


class ContributionAlreadyAssignedError(ConflictError):
    """Attribution refusée : la contribution est déjà rattachée à une personne. Seule une contribution orpheline s'attribue."""

    def __init__(self, contribution_id: int, owner_person_id: int) -> None:
        self.contribution_id = contribution_id
        self.owner_person_id = owner_person_id
        super().__init__(
            f"La contribution #{contribution_id} est déjà attribuée à la personne "
            f"#{owner_person_id} ; seule une contribution orpheline peut être attribuée."
        )


class PersonAlreadyInPublicationError(ConflictError):
    """Attribution refusée : la personne a déjà, dans la publication, une contribution rattachée à la main. Une personne a au plus une contribution par publication."""

    def __init__(self, publication_id: int, contribution_id: int) -> None:
        self.publication_id = publication_id
        self.contribution_id = contribution_id
        super().__init__("Cette personne est déjà rattachée à cette publication.")


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
