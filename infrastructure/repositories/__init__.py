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

Les agrégats Address, Config et Structure ne sont exposés qu'en async
(seuls consommateurs = routers API). Authorship, Journal, Person et
Publication existent dans les deux variantes (sync pour pipeline/CLI,
async pour API).
"""

from typing import Any

from domain.ports.address_repository import AsyncAddressRepository
from domain.ports.authorship_repository import AsyncAuthorshipRepository, AuthorshipRepository
from domain.ports.config_repository import AsyncConfigRepository
from domain.ports.journal_repository import AsyncJournalRepository, JournalRepository
from domain.ports.person_repository import AsyncPersonRepository, PersonRepository
from domain.ports.publication_repository import AsyncPublicationRepository, PublicationRepository
from domain.ports.publisher_repository import AsyncPublisherRepository, PublisherRepository
from domain.ports.structure_repository import AsyncStructureRepository

from .async_address_repository import PgAsyncAddressRepository
from .async_authorship_repository import PgAsyncAuthorshipRepository
from .async_config_repository import PgAsyncConfigRepository
from .async_journal_repository import PgAsyncJournalRepository
from .async_person_repository import PgAsyncPersonRepository
from .async_publication_repository import PgAsyncPublicationRepository
from .async_publisher_repository import PgAsyncPublisherRepository
from .async_structure_repository import PgAsyncStructureRepository
from .authorship_repository import PgAuthorshipRepository
from .journal_repository import PgJournalRepository
from .person_repository import PgPersonRepository
from .publication_repository import PgPublicationRepository
from .publisher_repository import PgPublisherRepository


def authorship_repository(cur: Any) -> AuthorshipRepository:
    """Retourne un AuthorshipRepository lié au curseur donné."""
    return PgAuthorshipRepository(cur)


def journal_repository(cur: Any) -> JournalRepository:
    """Retourne un JournalRepository lié au curseur donné."""
    return PgJournalRepository(cur)


def person_repository(cur: Any) -> PersonRepository:
    """Retourne un PersonRepository lié au curseur donné."""
    return PgPersonRepository(cur)


def publication_repository(cur: Any) -> PublicationRepository:
    """Retourne un PublicationRepository lié au curseur donné."""
    return PgPublicationRepository(cur)


def publisher_repository(cur: Any) -> PublisherRepository:
    """Retourne un PublisherRepository lié au curseur donné."""
    return PgPublisherRepository(cur)


# ── Factories async (§2.12) ────────────────────────────────────────


def async_address_repository(cur: Any) -> AsyncAddressRepository:
    return PgAsyncAddressRepository(cur)


def async_authorship_repository(cur: Any) -> AsyncAuthorshipRepository:
    return PgAsyncAuthorshipRepository(cur)


def async_config_repository(cur: Any) -> AsyncConfigRepository:
    return PgAsyncConfigRepository(cur)


def async_journal_repository(cur: Any) -> AsyncJournalRepository:
    return PgAsyncJournalRepository(cur)


def async_person_repository(cur: Any) -> AsyncPersonRepository:
    return PgAsyncPersonRepository(cur)


def async_publication_repository(cur: Any) -> AsyncPublicationRepository:
    return PgAsyncPublicationRepository(cur)


def async_publisher_repository(cur: Any) -> AsyncPublisherRepository:
    return PgAsyncPublisherRepository(cur)


def async_structure_repository(cur: Any) -> AsyncStructureRepository:
    return PgAsyncStructureRepository(cur)
