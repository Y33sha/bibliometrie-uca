"""Factories pour accéder aux implémentations concrètes des repositories.

La couche application importe ces fonctions plutôt que les classes
concrètes Pg* : elle ne dépend que de ce module (point de câblage
d'infrastructure) et des Protocols dans domain/ports/, jamais des
classes d'implémentation.

Pour changer d'implémentation (tests avec fake, futur changement de
SGBD…) : remplacer le corps d'une factory par la nouvelle impl, sans
toucher au code de l'application.

Usage :
    from infrastructure.repositories import person_repository

    def set_rejected(cur, person_id, rejected):
        person_repository(cur).set_rejected(person_id, rejected)
"""

from typing import Any

from domain.ports.address_repository import AddressRepository
from domain.ports.authorship_repository import AuthorshipRepository
from domain.ports.config_repository import ConfigRepository
from domain.ports.journal_repository import JournalRepository
from domain.ports.person_repository import PersonRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.structure_repository import StructureRepository

from .address_repository import PgAddressRepository
from .authorship_repository import PgAuthorshipRepository
from .config_repository import PgConfigRepository
from .journal_repository import PgJournalRepository
from .person_repository import PgPersonRepository
from .publication_repository import PgPublicationRepository
from .structure_repository import PgStructureRepository


def address_repository(cur: Any) -> AddressRepository:
    """Retourne un AddressRepository lié au curseur donné."""
    return PgAddressRepository(cur)


def authorship_repository(cur: Any) -> AuthorshipRepository:
    """Retourne un AuthorshipRepository lié au curseur donné."""
    return PgAuthorshipRepository(cur)


def config_repository(cur: Any) -> ConfigRepository:
    """Retourne un ConfigRepository lié au curseur donné."""
    return PgConfigRepository(cur)


def journal_repository(cur: Any) -> JournalRepository:
    """Retourne un JournalRepository lié au curseur donné."""
    return PgJournalRepository(cur)


def person_repository(cur: Any) -> PersonRepository:
    """Retourne un PersonRepository lié au curseur donné."""
    return PgPersonRepository(cur)


def publication_repository(cur: Any) -> PublicationRepository:
    """Retourne un PublicationRepository lié au curseur donné."""
    return PgPublicationRepository(cur)


def structure_repository(cur: Any) -> StructureRepository:
    """Retourne un StructureRepository lié au curseur donné."""
    return PgStructureRepository(cur)
