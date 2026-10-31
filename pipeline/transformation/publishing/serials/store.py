"""Store des revues : revue d'un ISSN-L, revue sans ISSN d'un titre ou d'un titre et d'un éditeur, type de la table `serials`, pour le pipeline.

L'édition dans l'administration passe par `infrastructure/repositories/serial_repository.py`, la fusion par `serial_merge`.
"""

from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import ColumnElement, Connection, any_, exists, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.normalize import normalize_text, to_plain_text
from domain.serials.serial import ManualField, SerialType
from infrastructure.db.scalars import scalar_int
from infrastructure.db.tables import serial_issns, serials
from infrastructure.sql_fragments import active_issns


class SerialSummary(NamedTuple):
    """Description d'une revue dans le journal du pipeline."""

    id: int
    title: str
    publisher: str | None
    issns: tuple[str, ...]
    """ISSN actifs."""


# Type modifiable par le pipeline : absent des champs saisis à la main.
TYPE_NOT_MANUAL = ~(literal(ManualField.SERIAL_TYPE.value) == any_(serials.c.manual_fields))
# Modèle OA modifiable par le pipeline : absent des champs saisis à la main.
OA_MODEL_NOT_MANUAL = ~(literal(ManualField.OA_MODEL.value) == any_(serials.c.manual_fields))

_SERIAL_SUMMARIES = text(f"""
    SELECT j.id, j.title, p.name AS publisher, {active_issns("j.id")} AS issns
    FROM serials j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE j.id = ANY(:ids)
""")


class SerialStore:
    """Requêtes sur les revues, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def serial_for_issnl(self, issnl: str, title: str) -> int:
        """Renvoie la revue de l'ISSN-L `issnl`, créée avec le titre `title` si elle manque. L'ISSN-L reçoit sa ligne de `serial_issns` au besoin."""
        self._conn.execute(
            pg_insert(serial_issns)
            .values(issn=issnl)
            .on_conflict_do_nothing(index_elements=["issn"])
        )
        serial_id: int | None = self._conn.execute(
            select(serial_issns.c.serial_id).where(serial_issns.c.issn == issnl)
        ).scalar_one()
        if serial_id is not None:
            return serial_id
        created = self._create_serial(title)
        self._conn.execute(
            update(serial_issns).where(serial_issns.c.issn == issnl).values(serial_id=created)
        )
        return created

    def serial_for_title(self, title: str) -> int:
        """Renvoie la revue sans ISSN de ce titre normalisé, créée si elle manque. Le plus petit identifiant départage deux revues."""
        return self._serial_without_issn(title, None)

    def serial_for_title_and_publisher(self, title: str, publisher_id: int | None) -> int:
        """Renvoie la revue sans ISSN de ce titre normalisé et de cet éditeur, créée si elle manque. Le plus petit identifiant départage deux revues."""
        return self._serial_without_issn(
            title, publisher_id, serials.c.publisher_id.is_not_distinct_from(publisher_id)
        )

    def _serial_without_issn(
        self, title: str, publisher_id: int | None, *conditions: ColumnElement[bool]
    ) -> int:
        """Renvoie la plus ancienne revue sans ISSN de ce titre normalisé qui remplit `conditions`, créée avec l'éditeur `publisher_id` si elle manque."""
        title = to_plain_text(title)
        found: int | None = self._conn.execute(
            select(serials.c.id)
            .where(
                serials.c.title_normalized == normalize_text(title),
                ~exists().where(serial_issns.c.serial_id == serials.c.id),
                *conditions,
            )
            .order_by(serials.c.id)
            .limit(1)
        ).scalar_one_or_none()
        if found is not None:
            return found
        return self._create_serial(title, publisher_id=publisher_id)

    def _create_serial(self, title: str, *, publisher_id: int | None = None) -> int:
        title = to_plain_text(title)
        return scalar_int(
            self._conn.execute(
                serials.insert()
                .values(
                    title=title,
                    title_normalized=normalize_text(title),
                    publisher_id=publisher_id,
                )
                .returning(serials.c.id)
            )
        )

    def set_serial_type_if_unknown(self, serial_id: int, serial_type: SerialType) -> None:
        """Pose le `serial_type` d'une revue encore de type inconnu."""
        self._conn.execute(
            update(serials)
            .where(
                serials.c.id == serial_id,
                serials.c.serial_type == SerialType.UNKNOWN,
                TYPE_NOT_MANUAL,
            )
            .values(serial_type=serial_type)
        )

    def set_serial_type(self, serial_id: int, serial_type: SerialType) -> None:
        """Pose le `serial_type` d'une revue, sans requalifier ses publications. L'édition par l'administration rejoue, elle, les corrections de `doc_type`."""
        self._conn.execute(
            update(serials)
            .where(serials.c.id == serial_id, TYPE_NOT_MANUAL)
            .values(serial_type=serial_type)
        )

    def describe_serials(self, serial_ids: Sequence[int]) -> dict[int, SerialSummary]:
        """Renvoie le titre, l'éditeur et les ISSN de chaque revue, pour la journalisation."""
        rows = self._conn.execute(_SERIAL_SUMMARIES, {"ids": list(serial_ids)}).all()
        return {r.id: SerialSummary(r.id, r.title, r.publisher, tuple(r.issns)) for r in rows}
