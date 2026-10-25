"""Store des revues : recherche, création, enrichissement, ISSN, formes de nom et type de la table `journals`, pour le pipeline.

L'édition dans l'administration et la fusion passent par `infrastructure/repositories/journal_repository.py`.
"""

from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Connection, any_, case, exists, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.journals.issns import IssnStatus, IssnSupport, JournalIssn
from domain.journals.journal import JournalType, ManualField, OaModel
from domain.normalize import normalize_text
from infrastructure.db.scalars import scalar_int
from infrastructure.db.tables import journal_issns, journal_name_forms, journals
from infrastructure.sql_fragments import active_issns


class JournalSummary(NamedTuple):
    """Ce que le journal du pipeline dit d'une revue."""

    id: int
    title: str
    publisher: str | None
    issns: tuple[str, ...]
    """ISSN actifs."""


# Le type n'est pas saisi à la main : le pipeline peut l'écrire.
TYPE_NOT_MANUAL = ~(literal(ManualField.JOURNAL_TYPE.value) == any_(journals.c.manual_fields))
# Le modèle OA n'est pas saisi à la main : le pipeline peut l'écrire.
_OA_MODEL_NOT_MANUAL = ~(literal(ManualField.OA_MODEL.value) == any_(journals.c.manual_fields))

_JOURNAL_SUMMARIES = text(f"""
    SELECT j.id, j.title, p.name AS publisher, {active_issns("j.id")} AS issns
    FROM journals j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE j.id = ANY(:ids)
""")


class JournalStore:
    """Revues, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── journal_name_forms ─────────────────────────────────────────

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
        """Ajoute une forme de nom normalisée pour une revue, si absente (idempotent). No-op si `form_normalized` est vide."""
        if not form_normalized:
            return
        stmt = (
            pg_insert(journal_name_forms)
            .values(
                journal_id=journal_id,
                form_normalized=form_normalized,
                publisher_id=publisher_id,
            )
            .on_conflict_do_nothing(index_elements=["form_normalized", "publisher_id"])
        )
        self._conn.execute(stmt)

    def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        """Cherche un `journal_id` par forme de nom normalisée. En cas d'ambiguïté, privilégie les revues à ISSN électronique actif. `publisher_id` fourni : restreint aux formes de cet éditeur ou sans éditeur."""
        stmt = (
            select(journal_name_forms.c.journal_id)
            .select_from(
                journal_name_forms.join(journals, journals.c.id == journal_name_forms.c.journal_id)
            )
            .where(journal_name_forms.c.form_normalized == form_normalized)
            .order_by(
                exists()
                .where(
                    journal_issns.c.journal_id == journals.c.id,
                    journal_issns.c.status == IssnStatus.ACTIVE,
                    journal_issns.c.support == IssnSupport.ELECTRONIC,
                )
                .desc(),
                journals.c.id.asc(),
            )
            .limit(1)
        )
        if publisher_id is not None:
            stmt = stmt.where(
                or_(
                    journal_name_forms.c.publisher_id == publisher_id,
                    journal_name_forms.c.publisher_id.is_(None),
                )
            )
        return self._conn.execute(stmt).scalar_one_or_none()

    # ── Recherche, création, enrichissement ────────────────────────

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None:
        return self._conn.execute(
            select(journals.c.id).where(journals.c.openalex_id == openalex_id)
        ).scalar_one_or_none()

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        """Cherche une revue qui a l'ISSN `issn_value`, quel que soit son statut, hors valeur mal formée. Une revue où l'ISSN est actif passe en premier."""
        return self._conn.execute(
            select(journal_issns.c.journal_id)
            .where(
                journal_issns.c.issn == issn_value,
                journal_issns.c.journal_id.is_not(None),
                journal_issns.c.status != IssnStatus.MALFORMED,
            )
            # Une revue où l'ISSN est actif passe avant une revue où il ne l'est pas.
            .order_by(
                case((journal_issns.c.status == IssnStatus.ACTIVE, 0), else_=1),
                journal_issns.c.journal_id,
            )
            .limit(1)
        ).scalar_one_or_none()

    def create_journal(
        self,
        *,
        title: str,
        openalex_id: str | None,
        oa_model: OaModel | None,
    ) -> int:
        """Insère un journal et retourne son id. `title_normalized` est dérivé de `title` ; l'éditeur se calcule d'après les publications (`refresh_journal_publishers`)."""
        stmt = (
            journals.insert()
            .values(
                title=title,
                title_normalized=normalize_text(title),
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            .returning(journals.c.id)
        )
        return scalar_int(self._conn.execute(stmt))

    def enrich_journal(
        self,
        journal_id: int,
        *,
        openalex_id: str | None = None,
        oa_model: OaModel | None = None,
    ) -> None:
        # L'UPDATE n'est émis que si au moins une colonne NULL recevrait une valeur.
        """Complète une revue existante avec les champs non nuls fournis, en COALESCE par champ : une valeur déjà en place est conservée."""
        fillable = (
            (journals.c.openalex_id, openalex_id),
            (journals.c.oa_model, oa_model),
        )
        null_targets = [col.is_(None) for col, value in fillable if value is not None]
        if not null_targets:
            return
        self._conn.execute(
            update(journals)
            .where(journals.c.id == journal_id, or_(*null_targets))
            .values(
                openalex_id=func.coalesce(journals.c.openalex_id, openalex_id),
                # Le littéral est lié au type de la colonne : `coalesce` ne le lui emprunte pas, et
                # `oa_model` est une enum, qu'un paramètre texte ne rejoint pas.
                # Un modèle OA saisi à la main reste, même vide.
                oa_model=case(
                    (
                        _OA_MODEL_NOT_MANUAL,
                        func.coalesce(
                            journals.c.oa_model, literal(oa_model, journals.c.oa_model.type)
                        ),
                    ),
                    else_=journals.c.oa_model,
                ),
            )
        )

    # ── ISSN ───────────────────────────────────────────────────────

    def issns_are_manual(self, journal_id: int) -> bool:
        """Les ISSN de la revue sont saisis à la main : ils font autorité, le pipeline ne les écrit pas."""
        return bool(
            self._conn.execute(
                select(literal(ManualField.ISSNS.value) == any_(journals.c.manual_fields)).where(
                    journals.c.id == journal_id
                )
            ).scalar()
        )

    def add_journal_issns(self, journal_id: int, issns: Sequence[JournalIssn]) -> None:
        """Ajoute à la revue les ISSN qu'elle n'a pas, sans date de vérification : ils attendent la vérification Sudoc. Une ligne sans revue de même ISSN est rattachée à la revue. Un ISSN déjà présent garde ses données ; il reçoit seulement le support qui lui manque."""
        if self.issns_are_manual(journal_id):
            return
        has_linking = self._conn.execute(
            select(
                exists().where(journal_issns.c.journal_id == journal_id, journal_issns.c.linking)
            )
        ).scalar_one()
        for row in issns:
            linking = row.linking and not has_linking
            has_linking = has_linking or linking
            carried = self._conn.execute(
                update(journal_issns)
                .where(journal_issns.c.journal_id == journal_id, journal_issns.c.issn == row.issn)
                .values(
                    support=func.coalesce(
                        journal_issns.c.support, literal(row.support, journal_issns.c.support.type)
                    ),
                    linking=journal_issns.c.linking | linking,
                )
            ).rowcount
            if carried:
                continue
            claimed = self._conn.execute(
                update(journal_issns)
                .where(journal_issns.c.journal_id.is_(None), journal_issns.c.issn == row.issn)
                .values(journal_id=journal_id, linking=linking)
            ).rowcount
            if not claimed:
                self._conn.execute(
                    pg_insert(journal_issns)
                    .values(
                        journal_id=journal_id,
                        issn=row.issn,
                        support=row.support,
                        linking=linking,
                        status=row.status,
                        replaced_by=row.replaced_by,
                    )
                    .on_conflict_do_nothing()
                )

    # ── Type ───────────────────────────────────────────────────────

    def set_journal_type_if_unknown(self, journal_id: int, journal_type: JournalType) -> None:
        """Pose le `journal_type` d'une revue encore de type inconnu."""
        self._conn.execute(
            update(journals)
            .where(
                journals.c.id == journal_id,
                journals.c.journal_type == JournalType.UNKNOWN,
                TYPE_NOT_MANUAL,
            )
            .values(journal_type=journal_type)
        )

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        """Pose le `journal_type` d'une revue. Écriture directe, sans requalification des publications — c'est l'édition admin, elle, qui rejoue les corrections de `doc_type`."""
        self._conn.execute(
            update(journals)
            .where(journals.c.id == journal_id, TYPE_NOT_MANUAL)
            .values(journal_type=journal_type)
        )

    # ── Journalisation ─────────────────────────────────────────────

    def describe_journals(self, journal_ids: Sequence[int]) -> dict[int, JournalSummary]:
        """Titre, éditeur et ISSN de chaque revue, pour la journalisation."""
        rows = self._conn.execute(_JOURNAL_SUMMARIES, {"ids": list(journal_ids)}).all()
        return {r.id: JournalSummary(r.id, r.title, r.publisher, tuple(r.issns)) for r in rows}
