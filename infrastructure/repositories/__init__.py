"""Factories pour accéder aux implémentations concrètes des repositories.

La couche application importe ces fonctions plutôt que les classes concrètes Pg* : elle ne dépend que de ce module (point de câblage d'infrastructure) et des Protocols dans application/ports/repositories/, jamais des classes d'implémentation.

Usage :
    from infrastructure.repositories import person_repository

    def set_rejected(cur, person_id, rejected):
        person_repository(cur).set_rejected(person_id, rejected)
"""

from sqlalchemy import Connection

from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.config_repository import ConfigRepository
from application.ports.repositories.doi_prefix_repository import DoiPrefixRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.person_repository import PersonRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.ports.repositories.structure_repository import StructureRepository

from .address_repository import PgAddressRepository
from .audit_repository import PgAuditRepository
from .authorship_repository import PgAuthorshipRepository
from .config_repository import PgConfigRepository
from .doi_prefix_repository import PgDoiPrefixRepository
from .journal_repository import PgJournalRepository
from .perimeter_repository import PgPerimeterRepository
from .person_repository import PgPersonRepository
from .publication_repository import PgPublicationRepository
from .publisher_repository import PgPublisherRepository
from .structure_repository import PgStructureRepository


def address_repository(conn: Connection) -> AddressRepository:
    return PgAddressRepository(conn)


def audit_repository(conn: Connection) -> AuditRepository:
    return PgAuditRepository(conn)


def authorship_repository(conn: Connection) -> AuthorshipRepository:
    return PgAuthorshipRepository(conn)


def config_repository(conn: Connection) -> ConfigRepository:
    return PgConfigRepository(conn)


def doi_prefix_repository(conn: Connection) -> DoiPrefixRepository:
    return PgDoiPrefixRepository(conn)


def journal_repository(conn: Connection) -> JournalRepository:
    return PgJournalRepository(conn)


def perimeter_repository(conn: Connection) -> PerimeterRepository:
    return PgPerimeterRepository(conn)


def person_repository(conn: Connection) -> PersonRepository:
    return PgPersonRepository(conn)


def publication_repository(conn: Connection) -> PublicationRepository:
    return PgPublicationRepository(conn)


def publisher_repository(conn: Connection) -> PublisherRepository:
    return PgPublisherRepository(conn)


def structure_repository(conn: Connection) -> StructureRepository:
    return PgStructureRepository(conn)
