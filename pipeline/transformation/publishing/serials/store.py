"""Store des revues : recherche, création, enrichissement, ISSN, formes de nom et type de la table `serials`, pour le pipeline.

L'édition dans l'administration passe par `infrastructure/repositories/serial_repository.py`, la fusion par `serial_merge`.
"""

from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Connection, any_, case, exists, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.normalize import normalize_text
from domain.serials.issns import IssnStatus, IssnSupport, SerialIssn
from domain.serials.serial import ManualField, OaModel, SerialType
from infrastructure.db.scalars import scalar_int
from infrastructure.db.tables import serial_issns, serial_name_forms, serials
from infrastructure.sql_fragments import active_issns


class SerialSummary(NamedTuple):
    """Ce que le journal du pipeline dit d'une revue."""

    id: int
    title: str
    publisher: str | None
    issns: tuple[str, ...]
    """ISSN actifs."""


# Le type n'est pas saisi à la main : le pipeline peut l'écrire.
TYPE_NOT_MANUAL = ~(literal(ManualField.SERIAL_TYPE.value) == any_(serials.c.manual_fields))
# Le modèle OA n'est pas saisi à la main : le pipeline peut l'écrire.
_OA_MODEL_NOT_MANUAL = ~(literal(ManualField.OA_MODEL.value) == any_(serials.c.manual_fields))

_SERIAL_SUMMARIES = text(f"""
    SELECT j.id, j.title, p.name AS publisher, {active_issns("j.id")} AS issns
    FROM serials j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE j.id = ANY(:ids)
""")


class SerialStore:
    """Revues, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add_serial_name_form(
        self,
        serial_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
        """Ajoute une forme de nom normalisée à une revue, si elle est absente et non vide."""
        if not form_normalized:
            return
        stmt = (
            pg_insert(serial_name_forms)
            .values(
                serial_id=serial_id,
                form_normalized=form_normalized,
                publisher_id=publisher_id,
            )
            .on_conflict_do_nothing(index_elements=["form_normalized", "publisher_id"])
        )
        self._conn.execute(stmt)

    def find_serial_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        """Revue d'une forme de nom normalisée. Une revue à ISSN électronique actif passe en premier. Avec un éditeur, seules comptent les formes de cet éditeur ou sans éditeur."""
        stmt = (
            select(serial_name_forms.c.serial_id)
            .select_from(
                serial_name_forms.join(serials, serials.c.id == serial_name_forms.c.serial_id)
            )
            .where(serial_name_forms.c.form_normalized == form_normalized)
            .order_by(
                exists()
                .where(
                    serial_issns.c.serial_id == serials.c.id,
                    serial_issns.c.status == IssnStatus.ACTIVE,
                    serial_issns.c.support == IssnSupport.ELECTRONIC,
                )
                .desc(),
                serials.c.id.asc(),
            )
            .limit(1)
        )
        if publisher_id is not None:
            stmt = stmt.where(
                or_(
                    serial_name_forms.c.publisher_id == publisher_id,
                    serial_name_forms.c.publisher_id.is_(None),
                )
            )
        return self._conn.execute(stmt).scalar_one_or_none()

    def find_serial_by_openalex_id(self, openalex_id: str) -> int | None:
        return self._conn.execute(
            select(serials.c.id).where(serials.c.openalex_id == openalex_id)
        ).scalar_one_or_none()

    def find_serial_by_issn_any(self, issn_value: str) -> int | None:
        """Revue qui a l'ISSN, quel que soit son statut, hors valeur mal formée. Une revue où l'ISSN est actif passe en premier."""
        return self._conn.execute(
            select(serial_issns.c.serial_id)
            .where(
                serial_issns.c.issn == issn_value,
                serial_issns.c.serial_id.is_not(None),
                serial_issns.c.status != IssnStatus.MALFORMED,
            )
            .order_by(
                case((serial_issns.c.status == IssnStatus.ACTIVE, 0), else_=1),
                serial_issns.c.serial_id,
            )
            .limit(1)
        ).scalar_one_or_none()

    def create_serial(
        self,
        *,
        title: str,
        openalex_id: str | None,
        oa_model: OaModel | None,
    ) -> int:
        """Insère une revue et rend son id. L'éditeur se calcule d'après les publications (`refresh_serial_publishers`)."""
        stmt = (
            serials.insert()
            .values(
                title=title,
                title_normalized=normalize_text(title),
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            .returning(serials.c.id)
        )
        return scalar_int(self._conn.execute(stmt))

    def enrich_serial(
        self,
        serial_id: int,
        *,
        openalex_id: str | None = None,
        oa_model: OaModel | None = None,
    ) -> None:
        """Complète les champs vides d'une revue avec les valeurs fournies ; une valeur déjà en place reste."""
        fillable = (
            (serials.c.openalex_id, openalex_id),
            (serials.c.oa_model, oa_model),
        )
        null_targets = [col.is_(None) for col, value in fillable if value is not None]
        if not null_targets:
            return
        self._conn.execute(
            update(serials)
            .where(serials.c.id == serial_id, or_(*null_targets))
            .values(
                openalex_id=func.coalesce(serials.c.openalex_id, openalex_id),
                # Le littéral reçoit le type enum de la colonne ; sans lui, `coalesce` reçoit un paramètre texte.
                # Un modèle OA saisi à la main reste, même vide.
                oa_model=case(
                    (
                        _OA_MODEL_NOT_MANUAL,
                        func.coalesce(
                            serials.c.oa_model, literal(oa_model, serials.c.oa_model.type)
                        ),
                    ),
                    else_=serials.c.oa_model,
                ),
            )
        )

    def issns_are_manual(self, serial_id: int) -> bool:
        """Vrai si les ISSN de la revue sont saisis à la main : ils font autorité, et le pipeline les laisse."""
        return bool(
            self._conn.execute(
                select(literal(ManualField.ISSNS.value) == any_(serials.c.manual_fields)).where(
                    serials.c.id == serial_id
                )
            ).scalar()
        )

    def add_serial_issns(self, serial_id: int, issns: Sequence[SerialIssn]) -> None:
        """Ajoute à la revue les ISSN qu'elle n'a pas, sans date de vérification : ils attendent la vérification Sudoc. Une ligne sans revue de même ISSN est rattachée à la revue. Un ISSN déjà présent garde ses données ; il reçoit seulement le support qui lui manque."""
        if self.issns_are_manual(serial_id):
            return
        has_linking = self._conn.execute(
            select(exists().where(serial_issns.c.serial_id == serial_id, serial_issns.c.linking))
        ).scalar_one()
        for row in issns:
            linking = row.linking and not has_linking
            has_linking = has_linking or linking
            carried = self._conn.execute(
                update(serial_issns)
                .where(serial_issns.c.serial_id == serial_id, serial_issns.c.issn == row.issn)
                .values(
                    support=func.coalesce(
                        serial_issns.c.support, literal(row.support, serial_issns.c.support.type)
                    ),
                    linking=serial_issns.c.linking | linking,
                )
            ).rowcount
            if carried:
                continue
            claimed = self._conn.execute(
                update(serial_issns)
                .where(serial_issns.c.serial_id.is_(None), serial_issns.c.issn == row.issn)
                .values(serial_id=serial_id, linking=linking)
            ).rowcount
            if not claimed:
                self._conn.execute(
                    pg_insert(serial_issns)
                    .values(
                        serial_id=serial_id,
                        issn=row.issn,
                        support=row.support,
                        linking=linking,
                        status=row.status,
                    )
                    .on_conflict_do_nothing()
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
        """Titre, éditeur et ISSN de chaque revue, pour la journalisation."""
        rows = self._conn.execute(_SERIAL_SUMMARIES, {"ids": list(serial_ids)}).all()
        return {r.id: SerialSummary(r.id, r.title, r.publisher, tuple(r.issns)) for r in rows}
