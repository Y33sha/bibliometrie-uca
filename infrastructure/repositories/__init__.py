"""Factories pour accéder aux implémentations concrètes des repositories.

La couche application importe ces fonctions plutôt que les classes concrètes Pg* : elle ne dépend que de ce module (point de câblage d'infrastructure) et des Protocols dans application/ports/repositories/, jamais des classes d'implémentation.

Usage :
    from infrastructure.repositories import person_repository

    def set_exclusion(conn, person_id, exclusion):
        person_repository(conn).set_exclusion(person_id, exclusion)
"""

from sqlalchemy import Connection

from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.config_repository import ConfigRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.person_repository import PersonRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.ports.repositories.serial_repository import SerialRepository
from application.ports.repositories.structure_repository import StructureRepository
from application.ports.repositories.user_repository import UserRepository

from .address_repository import PgAddressRepository
from .audit_repository import PgAuditRepository
from .config_repository import PgConfigRepository
from .contribution_repository import PgContributionRepository
from .perimeter_repository import PgPerimeterRepository
from .person_repository import PgPersonRepository
from .publisher_repository import PgPublisherRepository
from .serial_repository import PgSerialRepository
from .structure_repository import PgStructureRepository
from .user_repository import PgUserRepository


def address_repository(conn: Connection) -> AddressRepository:
    return PgAddressRepository(conn)


def audit_repository(conn: Connection) -> AuditRepository:
    return PgAuditRepository(conn)


def contribution_repository(conn: Connection) -> ContributionRepository:
    return PgContributionRepository(conn)


def config_repository(conn: Connection) -> ConfigRepository:
    return PgConfigRepository(conn)


def serial_repository(conn: Connection) -> SerialRepository:
    return PgSerialRepository(conn)


def perimeter_repository(conn: Connection) -> PerimeterRepository:
    return PgPerimeterRepository(conn)


def person_repository(conn: Connection) -> PersonRepository:
    return PgPersonRepository(conn)


def publisher_repository(conn: Connection) -> PublisherRepository:
    return PgPublisherRepository(conn)


def structure_repository(conn: Connection) -> StructureRepository:
    return PgStructureRepository(conn)


def user_repository(conn: Connection) -> UserRepository:
    return PgUserRepository(conn)
