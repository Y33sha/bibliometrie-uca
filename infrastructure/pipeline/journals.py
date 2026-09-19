"""Adapter PostgreSQL de la table `journals` pour le pipeline.

Sert les contrats pipeline (`application/ports/pipeline/journals.py`) : trouve-ou-crée d'une revue à partir des sources, enrichissement OpenAlex (typage + APC), vérification des ISSN dans le Sudoc et import du dump DOAJ. La table étant mono-adapter, une seule classe implémente tous les Protocols. L'édition dans l'administration et la fusion passent par `infrastructure/repositories/journal_repository.py`.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import Connection, case, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.pipeline.journals import (
    JournalCleanupQueries,
    JournalDoajQueries,
    JournalFindOrCreateQueries,
    JournalIssnGroup,
    JournalIssnRow,
    JournalMergeCandidate,
    JournalMergeGroup,
    JournalMergeQueries,
    JournalOpenAlexEnrichmentQueries,
    JournalProceedingsTypingQueries,
    JournalPublicationPair,
    JournalRecordTypes,
    JournalSudocQueries,
    JournalSudocRow,
    JournalSummary,
    JournalTitleIssnRow,
    JournalTitleRow,
)
from domain.journals.journal import JournalType, OaModel
from domain.normalize import normalize_text
from domain.types import JsonValue
from infrastructure.db.scalars import scalar_datetime_or_none, scalar_int
from infrastructure.db.tables import journal_name_forms, journals

# Revues à vérifier dans le Sudoc, avec les ISSN de leurs enregistrements absents de leurs ISSN.
_JOURNALS_TO_CHECK_IN_SUDOC = text("""
    WITH paires AS (
        SELECT DISTINCT s.journal_id, v.issn
        FROM source_publications s
        CROSS JOIN LATERAL jsonb_array_elements_text(s.external_ids->'issn') AS v(issn)
        WHERE s.journal_id IS NOT NULL
    ), documents AS (
        SELECT p.journal_id, array_agg(p.issn ORDER BY p.issn) AS issns
        FROM paires p
        JOIN journals j ON j.id = p.journal_id
        WHERE p.issn <> coalesce(j.issn, '')
          AND p.issn <> coalesce(j.eissn, '')
          AND p.issn <> coalesce(j.issnl, '')
          AND NOT (p.issn = ANY(j.rejected_issns))
        GROUP BY p.journal_id
    )
    SELECT j.id, j.title, j.issn, j.eissn, j.issnl, j.rejected_issns,
           coalesce(d.issns, ARRAY[]::text[]) AS document_issns
    FROM journals j
    LEFT JOIN documents d ON d.journal_id = j.id
    WHERE d.issns IS NOT NULL
       OR (j.sudoc_checked_at IS NULL
           AND (j.issn IS NOT NULL OR j.eissn IS NOT NULL OR j.issnl IS NOT NULL
                OR cardinality(j.rejected_issns) > 0))
    ORDER BY j.id
""")


# Revues vérifiées qui partagent leur ISSN-L, la cible de la fusion en tête de chaque groupe.
_JOURNALS_SHARING_ISSNL = text("""
    SELECT issnl, array_agg(id ORDER BY pub_count DESC, id) AS ids
    FROM journals
    WHERE issnl IS NOT NULL AND sudoc_checked_at IS NOT NULL
    GROUP BY issnl
    HAVING count(*) > 1
    ORDER BY issnl
""")


# Revues vérifiées qui portent le même ISSN dans `issn` ou `eissn`, la cible de la fusion en tête.
_JOURNALS_SHARING_COLUMN_ISSN = text("""
    WITH colonnes AS (
        SELECT DISTINCT id, title, pub_count, v AS issn
        FROM journals, LATERAL (VALUES (issn), (eissn)) AS colonne(v)
        WHERE v IS NOT NULL AND sudoc_checked_at IS NOT NULL
    )
    SELECT issn,
           array_agg(id ORDER BY pub_count DESC, id) AS ids,
           array_agg(title ORDER BY pub_count DESC, id) AS titles
    FROM colonnes
    GROUP BY issn
    HAVING count(*) > 1
    ORDER BY issn
""")


# Paires de revues vérifiées dont l'une porte parmi ses ISSN rejetés un ISSN que l'autre porte dans ses
# colonnes. La cible de la fusion en tête : la revue dont le premier document est le plus tardif, puis celle
# qui porte le plus de publications.
_JOURNALS_SHARING_A_REJECTED_ISSN = text("""
    WITH verifiees AS (
        SELECT id, issn, eissn, issnl, rejected_issns
        FROM journals
        WHERE sudoc_checked_at IS NOT NULL
    ), paires AS (
        SELECT DISTINCT r.issn, least(a.id, b.id) AS x_id, greatest(a.id, b.id) AS y_id
        FROM verifiees a
        CROSS JOIN LATERAL unnest(a.rejected_issns) AS r(issn)
        JOIN verifiees b ON b.id <> a.id AND r.issn IN (b.issn, b.eissn, b.issnl)
    ), revues AS (
        SELECT j.id, j.pub_count,
               (SELECT min(s.pub_year) FROM source_publications s WHERE s.journal_id = j.id)
                   AS premiere_annee
        FROM journals j
        WHERE j.id IN (SELECT x_id FROM paires UNION SELECT y_id FROM paires)
    )
    SELECT p.issn,
           (SELECT array_agg(r.id ORDER BY r.premiere_annee DESC NULLS LAST, r.pub_count DESC, r.id)
            FROM revues r WHERE r.id IN (p.x_id, p.y_id)) AS ids
    FROM paires p
    ORDER BY p.issn
""")


# Paires de revues seules à porter leur titre, dont au moins une sans ISSN, et dont les
# enregistrements partagent un préfixe DOI. La cible de la fusion en tête. Un titre normalisé vide
# (alphabet non latin, symboles) ne rapproche aucune revue.
_SAME_TITLE_DUPLICATES = text("""
    WITH prefixes AS (
        SELECT journal_id AS id, array_agg(DISTINCT split_part(doi, '/', 1)) AS pfx
        FROM source_publications
        WHERE journal_id IS NOT NULL AND doi IS NOT NULL
        GROUP BY journal_id
    ), paires_de_titre AS (
        SELECT title_normalized FROM journals
        WHERE title_normalized <> ''
        GROUP BY title_normalized
        HAVING count(*) = 2
    ), revues AS (
        SELECT j.id, j.title_normalized, j.pub_count,
               (j.issn IS NOT NULL OR j.eissn IS NOT NULL) AS a_issn,
               p.pfx
        FROM journals j
        JOIN paires_de_titre USING (title_normalized)
        JOIN prefixes p ON p.id = j.id
    )
    SELECT x.title_normalized,
           (SELECT array_agg(r.id ORDER BY r.pub_count DESC, r.a_issn DESC, r.id)
            FROM revues r WHERE r.id IN (x.id, y.id)) AS ids
    FROM revues x
    JOIN revues y ON y.title_normalized = x.title_normalized AND x.id < y.id
    WHERE NOT (x.a_issn AND y.a_issn) AND x.pfx && y.pfx
    ORDER BY x.title_normalized
""")

# Paires de revues que les enregistrements d'une même publication portent, les plus partagées en tête.
_JOURNALS_SHARING_A_PUBLICATION = text("""
    WITH rattachements AS (
        SELECT DISTINCT publication_id, journal_id
        FROM source_publications
        WHERE publication_id IS NOT NULL AND journal_id IS NOT NULL
    ), paires AS (
        SELECT a.journal_id AS first_id, b.journal_id AS second_id, count(*) AS publications
        FROM rattachements a
        JOIN rattachements b ON b.publication_id = a.publication_id AND a.journal_id < b.journal_id
        GROUP BY a.journal_id, b.journal_id
    )
    SELECT p.publications,
           x.id AS first_id, x.title AS first_title, x.pub_count AS first_pub_count,
           array_remove(ARRAY[x.issn, x.eissn, x.issnl], NULL) AS first_issns,
           y.id AS second_id, y.title AS second_title, y.pub_count AS second_pub_count,
           array_remove(ARRAY[y.issn, y.eissn, y.issnl], NULL) AS second_issns
    FROM paires p
    JOIN journals x ON x.id = p.first_id
    JOIN journals y ON y.id = p.second_id
    ORDER BY p.publications DESC, p.first_id, p.second_id
""")

_JOURNAL_SUMMARIES = text("""
    SELECT j.id, j.title, p.name AS publisher, j.issn, j.eissn
    FROM journals j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE j.id = ANY(:ids)
""")

# Revues sans enregistrement, sans publication et sans paiement APC ; leurs formes de nom partent avec
# elles (`ON DELETE CASCADE`).
_DELETE_EMPTY_JOURNALS = text("""
    WITH supprimees AS (
        DELETE FROM journals j
        WHERE NOT EXISTS (SELECT 1 FROM source_publications s WHERE s.journal_id = j.id)
          AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.journal_id = j.id)
          AND NOT EXISTS (SELECT 1 FROM apc_payments a WHERE a.journal_id = j.id)
        RETURNING j.id, j.title, j.publisher_id, j.issn, j.eissn
    )
    SELECT s.id, s.title, p.name AS publisher, s.issn, s.eissn
    FROM supprimees s LEFT JOIN publishers p ON p.id = s.publisher_id
    ORDER BY s.id
""")


# Type brut de chaque document des revues de type inconnu : celui de la source, avant correction.
_RECORD_TYPES_OF_UNKNOWN_JOURNALS = text("""
    SELECT j.id,
           array_agg(s.source::text ORDER BY s.id) AS sources,
           array_agg(coalesce(s.raw_metadata->'doc_type'->>'raw', s.doc_type) ORDER BY s.id)
               AS raw_types
    FROM journals j
    JOIN source_publications s ON s.journal_id = j.id
    WHERE j.journal_type = 'unknown'
    GROUP BY j.id
    ORDER BY j.id
""")


class PgJournalGatewayQueries(
    JournalFindOrCreateQueries,
    JournalOpenAlexEnrichmentQueries,
    JournalSudocQueries,
    JournalMergeQueries,
    JournalCleanupQueries,
    JournalProceedingsTypingQueries,
    JournalDoajQueries,
):
    """Accès PostgreSQL à `journals` pour le pipeline, via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── journal_name_forms ─────────────────────────────────────────

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
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
        stmt = (
            select(journal_name_forms.c.journal_id)
            .select_from(
                journal_name_forms.join(journals, journals.c.id == journal_name_forms.c.journal_id)
            )
            .where(journal_name_forms.c.form_normalized == form_normalized)
            .order_by(
                case((journals.c.eissn.is_not(None), 1), else_=0).desc(),
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

    def find_proceedings_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        stmt = (
            select(journal_name_forms.c.journal_id)
            .select_from(
                journal_name_forms.join(journals, journals.c.id == journal_name_forms.c.journal_id)
            )
            .where(
                journal_name_forms.c.form_normalized == form_normalized,
                journals.c.journal_type == JournalType.PROCEEDINGS,
            )
            .order_by(journals.c.id.asc())
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

    # ── journals ───────────────────────────────────────────────────

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None:
        return self._conn.execute(
            select(journals.c.id).where(journals.c.openalex_id == openalex_id)
        ).scalar_one_or_none()

    def find_journals_of_unknown_type(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        rows = self._conn.execute(
            select(journals.c.id, journals.c.openalex_id)
            .where(journals.c.openalex_id.is_not(None))
            .where(journals.c.journal_type == "unknown")
            .order_by(journals.c.id)
            .limit(limit or None)
        ).all()
        return [(r.id, r.openalex_id) for r in rows]

    def find_journal_issn_index(self) -> list[JournalIssnRow]:
        return [
            JournalIssnRow(r.id, r.issn, r.eissn, r.issnl)
            for r in self._conn.execute(
                select(journals.c.id, journals.c.issn, journals.c.eissn, journals.c.issnl).where(
                    or_(
                        journals.c.issn.is_not(None),
                        journals.c.eissn.is_not(None),
                        journals.c.issnl.is_not(None),
                    )
                )
            ).all()
        ]

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        in_columns = or_(
            journals.c.issn == issn_value,
            journals.c.eissn == issn_value,
            journals.c.issnl == issn_value,
        )
        return self._conn.execute(
            select(journals.c.id)
            .where(or_(in_columns, journals.c.rejected_issns.any(issn_value)))
            # Une revue qui porte l'ISSN dans ses colonnes passe avant une revue qui l'a rejeté.
            .order_by(case((in_columns, 0), else_=1))
            .limit(1)
        ).scalar_one_or_none()

    def enrich_journal(
        self,
        journal_id: int,
        *,
        issn: str | None = None,
        eissn: str | None = None,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: OaModel | None = None,
    ) -> None:
        carried = self._conn.execute(
            select(journals.c.issn, journals.c.eissn, journals.c.rejected_issns).where(
                journals.c.id == journal_id
            )
        ).one_or_none()
        new_issn = False
        if carried is not None:
            # Un ISSN que la revue porte déjà dans `issn` ou `eissn`, ou qu'elle a rejeté, n'est
            # pas réécrit dans une colonne : la vérification Sudoc a rangé chaque ISSN. `issnl`
            # reste hors de la comparaison, l'ISSN-L étant lui-même l'ISSN d'un support.
            known = {v for v in (carried.issn, carried.eissn, *carried.rejected_issns) if v}
            issn = None if issn in known else issn
            eissn = None if eissn in known or eissn == issn else eissn
            new_issn = (issn is not None and carried.issn is None) or (
                eissn is not None and carried.eissn is None
            )
        # L'UPDATE n'est émis que si au moins une colonne NULL recevrait une valeur.
        fillable = (
            (journals.c.issn, issn),
            (journals.c.eissn, eissn),
            (journals.c.publisher_id, publisher_id),
            (journals.c.openalex_id, openalex_id),
            (journals.c.oa_model, oa_model),
        )
        null_targets = [col.is_(None) for col, value in fillable if value is not None]
        if not null_targets:
            return
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id, or_(*null_targets))
            .values(
                issn=func.coalesce(journals.c.issn, issn),
                eissn=func.coalesce(journals.c.eissn, eissn),
                publisher_id=func.coalesce(journals.c.publisher_id, publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, openalex_id),
                # Le littéral est lié au type de la colonne : `coalesce` ne le lui emprunte pas, et
                # `oa_model` est une enum, qu'un paramètre texte ne rejoint pas.
                oa_model=func.coalesce(
                    journals.c.oa_model, literal(oa_model, journals.c.oa_model.type)
                ),
                # Un ISSN nouveau remet la revue à vérifier dans le Sudoc.
                **({"sudoc_checked_at": None} if new_issn else {}),
            )
        )
        self._conn.execute(stmt)

    def add_rejected_issns(self, journal_id: int, values: Sequence[str]) -> None:
        if not values:
            return
        self._conn.execute(
            text(
                "UPDATE journals SET rejected_issns = ARRAY("
                "SELECT v FROM (SELECT DISTINCT unnest(rejected_issns || CAST(:values AS text[])) AS v) d "
                'ORDER BY v COLLATE "C"'
                "), "
                # Une valeur nouvelle remet la revue à vérifier dans le Sudoc.
                "sudoc_checked_at = CASE WHEN CAST(:values AS text[]) <@ rejected_issns "
                "THEN sudoc_checked_at END "
                "WHERE id = :id"
            ),
            {"id": journal_id, "values": list(values)},
        )

    def find_journals_to_check_in_sudoc(self) -> list[JournalSudocRow]:
        rows = self._conn.execute(_JOURNALS_TO_CHECK_IN_SUDOC).all()
        return [
            JournalSudocRow(
                r.id,
                r.title,
                r.issn,
                r.eissn,
                r.issnl,
                tuple(r.rejected_issns),
                tuple(r.document_issns),
            )
            for r in rows
        ]

    def record_sudoc_check(
        self,
        journal_id: int,
        *,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        rejected_issns: Sequence[str],
        checked_at: datetime,
    ) -> None:
        self._conn.execute(
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                issn=issn,
                eissn=eissn,
                issnl=issnl,
                rejected_issns=list(rejected_issns),
                sudoc_checked_at=checked_at,
            )
        )

    # ── typage en recueil d'actes ──────────────────────────────────

    def find_record_types_of_unknown_journals(self) -> list[JournalRecordTypes]:
        return [
            JournalRecordTypes(r.id, tuple(zip(r.sources, r.raw_types, strict=True)))
            for r in self._conn.execute(_RECORD_TYPES_OF_UNKNOWN_JOURNALS)
        ]

    def find_titles_of_non_proceedings_journals(self) -> list[JournalTitleIssnRow]:
        rows = self._conn.execute(
            select(
                journals.c.id,
                journals.c.title,
                or_(
                    journals.c.issn.is_not(None),
                    journals.c.eissn.is_not(None),
                    journals.c.issnl.is_not(None),
                ).label("has_issn"),
            )
            .where(journals.c.journal_type != JournalType.PROCEEDINGS)
            .order_by(journals.c.id)
        )
        return [JournalTitleIssnRow(r.id, r.title, r.has_issn) for r in rows]

    # ── fusion ─────────────────────────────────────────────────────

    def find_journals_sharing_issnl(self) -> list[JournalMergeGroup]:
        return [
            JournalMergeGroup(r.issnl, tuple(r.ids))
            for r in self._conn.execute(_JOURNALS_SHARING_ISSNL).all()
        ]

    def find_same_title_duplicates(self) -> list[JournalMergeGroup]:
        return [
            JournalMergeGroup(r.title_normalized, tuple(r.ids))
            for r in self._conn.execute(_SAME_TITLE_DUPLICATES).all()
        ]

    def find_journals_sharing_a_rejected_issn(self) -> list[JournalMergeGroup]:
        return [
            JournalMergeGroup(r.issn, tuple(r.ids))
            for r in self._conn.execute(_JOURNALS_SHARING_A_REJECTED_ISSN).all()
        ]

    def find_journals_sharing_a_publication(self) -> list[JournalPublicationPair]:
        return [
            JournalPublicationPair(
                JournalMergeCandidate(
                    r.first_id, r.first_title, frozenset(r.first_issns), r.first_pub_count
                ),
                JournalMergeCandidate(
                    r.second_id, r.second_title, frozenset(r.second_issns), r.second_pub_count
                ),
                r.publications,
            )
            for r in self._conn.execute(_JOURNALS_SHARING_A_PUBLICATION).all()
        ]

    def describe_journals(self, journal_ids: Sequence[int]) -> dict[int, JournalSummary]:
        rows = self._conn.execute(_JOURNAL_SUMMARIES, {"ids": list(journal_ids)}).all()
        return {r.id: JournalSummary(r.id, r.title, r.publisher, r.issn, r.eissn) for r in rows}

    # ── nettoyage ──────────────────────────────────────────────────

    def delete_empty_journals(self) -> list[JournalSummary]:
        return [
            JournalSummary(r.id, r.title, r.publisher, r.issn, r.eissn)
            for r in self._conn.execute(_DELETE_EMPTY_JOURNALS).all()
        ]

    def find_journals_sharing_column_issn(self) -> list[JournalIssnGroup]:
        return [
            JournalIssnGroup(
                r.issn, tuple(JournalTitleRow(i, t) for i, t in zip(r.ids, r.titles, strict=True))
            )
            for r in self._conn.execute(_JOURNALS_SHARING_COLUMN_ISSN).all()
        ]

    def create_journal(
        self,
        *,
        title: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: OaModel | None,
    ) -> int:
        """Insère un journal et retourne son id. `title_normalized` est dérivé de `title`."""
        stmt = (
            journals.insert()
            .values(
                title=title,
                title_normalized=normalize_text(title),
                issn=issn,
                eissn=eissn,
                issnl=issnl,
                publisher_id=publisher_id,
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            .returning(journals.c.id)
        )
        return scalar_int(self._conn.execute(stmt))

    # ── Enrichissement OpenAlex ────────────────────────────────────

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
    ) -> None:
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                apc_amount=func.coalesce(apc_amount, journals.c.apc_amount),
                apc_currency=func.coalesce(apc_currency, journals.c.apc_currency),
            )
        )
        self._conn.execute(stmt)

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        self._conn.execute(
            update(journals).where(journals.c.id == journal_id).values(journal_type=journal_type)
        )

    # ── Import DOAJ ────────────────────────────────────────────────

    def update_journal_doaj(
        self,
        journal_id: int,
        *,
        payload: Mapping[str, JsonValue] | None,
        imported_at: datetime,
        is_in_doaj: bool,
    ) -> None:
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                doaj_payload=payload,
                doaj_imported_at=imported_at,
                is_in_doaj=is_in_doaj,
            )
        )
        self._conn.execute(stmt)

    def reset_is_in_doaj(self) -> int:
        return self._conn.execute(
            update(journals).where(journals.c.is_in_doaj).values(is_in_doaj=False)
        ).rowcount

    def doaj_last_import_at(self) -> datetime | None:
        return scalar_datetime_or_none(
            self._conn.execute(select(func.max(journals.c.doaj_imported_at)))
        )
