"""Adapter PostgreSQL de la table `journals` pour le pipeline.

Sert les contrats pipeline (`application/ports/pipeline/journals.py`) : trouve-ou-crée d'une revue à partir des sources, enrichissement OpenAlex (typage + APC), vérification des ISSN dans le Sudoc et import du dump DOAJ. La table étant mono-adapter, une seule classe implémente tous les Protocols. L'édition dans l'administration et la fusion passent par `infrastructure/repositories/journal_repository.py`.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import Connection, case, delete, exists, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.pipeline.journals import (
    DoiJournalRow,
    JournalCleanupQueries,
    JournalDoajQueries,
    JournalDoiNamespaceQueries,
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
    JournalTitleTypeRow,
)
from domain.journals.doi_namespaces import DoiNamespace
from domain.journals.issns import IssnStatus, IssnSupport, JournalIssn
from domain.journals.journal import JournalType, OaModel
from domain.normalize import normalize_text
from domain.publications.identifiers import ISSN
from domain.types import JsonValue
from infrastructure.db.journal_issns import issn_values, issns_by_journal
from infrastructure.db.scalars import scalar_datetime_or_none, scalar_int
from infrastructure.db.sql_fragments import active_issns, has_active_issn
from infrastructure.db.tables import (
    journal_doi_namespaces,
    journal_issns,
    journal_name_forms,
    journals,
)

# ISSN des enregistrements de chaque revue, toutes sources, tels que reçus : `find_journals_to_check_in_sudoc` les normalise.
_DOCUMENT_ISSNS = text("""
    SELECT DISTINCT s.journal_id, trim(v.issn) AS issn
    FROM source_publications s
    CROSS JOIN LATERAL (
        VALUES (s.biblio->'journal'->>'issn'), (s.biblio->'journal'->>'eissn')
    ) AS v(issn)
    WHERE s.journal_id IS NOT NULL AND v.issn IS NOT NULL
""")

# Revues dont un ISSN n'est pas vérifié dans le Sudoc.
_JOURNALS_WITH_UNCHECKED_ISSNS = text("""
    SELECT DISTINCT journal_id FROM journal_issns
    WHERE journal_id IS NOT NULL AND sudoc_checked_at IS NULL
""")

# Revues vérifiées dans le Sudoc : tous leurs ISSN portent une date de vérification.
_VERIFIED = """
    verifiees AS (
        SELECT journal_id AS id FROM journal_issns
        WHERE journal_id IS NOT NULL
        GROUP BY journal_id
        HAVING bool_and(sudoc_checked_at IS NOT NULL)
    )
"""

# Revues vérifiées qui partagent leur ISSN-L, la cible de la fusion en tête de chaque groupe.
_JOURNALS_SHARING_ISSNL = text(f"""
    WITH {_VERIFIED}
    SELECT i.issn AS issnl, array_agg(j.id ORDER BY j.pub_count DESC, j.id) AS ids
    FROM journal_issns i
    JOIN verifiees v ON v.id = i.journal_id
    JOIN journals j ON j.id = i.journal_id
    WHERE i.linking
    GROUP BY i.issn
    HAVING count(*) > 1
    ORDER BY i.issn
""")


# Revues vérifiées où le même ISSN est actif, la cible de la fusion en tête.
_JOURNALS_SHARING_ACTIVE_ISSN = text(f"""
    WITH {_VERIFIED}
    SELECT i.issn,
           array_agg(j.id ORDER BY j.pub_count DESC, j.id) AS ids,
           array_agg(j.title ORDER BY j.pub_count DESC, j.id) AS titles
    FROM journal_issns i
    JOIN verifiees v ON v.id = i.journal_id
    JOIN journals j ON j.id = i.journal_id
    WHERE i.status = 'active'
    GROUP BY i.issn
    HAVING count(*) > 1
    ORDER BY i.issn
""")


# Paires de revues vérifiées dont l'une porte, inactif, un ISSN actif dans l'autre. La cible de la fusion en tête : la
# revue dont le premier document est le plus tardif, puis celle qui porte le plus de publications.
_JOURNALS_SHARING_AN_INACTIVE_ISSN = text(f"""
    WITH {_VERIFIED}, paires AS (
        SELECT DISTINCT a.issn, least(a.journal_id, b.journal_id) AS x_id,
               greatest(a.journal_id, b.journal_id) AS y_id
        FROM journal_issns a
        JOIN verifiees va ON va.id = a.journal_id
        JOIN journal_issns b ON b.issn = a.issn AND b.journal_id <> a.journal_id
        JOIN verifiees vb ON vb.id = b.journal_id
        WHERE a.status NOT IN ('active', 'malformed') AND b.status = 'active'
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
_SAME_TITLE_DUPLICATES = text(f"""
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
               {has_active_issn("j.id")} AS a_issn,
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
_JOURNALS_SHARING_A_PUBLICATION = text(f"""
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
           {active_issns("x.id")} AS first_issns,
           y.id AS second_id, y.title AS second_title, y.pub_count AS second_pub_count,
           {active_issns("y.id")} AS second_issns
    FROM paires p
    JOIN journals x ON x.id = p.first_id
    JOIN journals y ON y.id = p.second_id
    ORDER BY p.publications DESC, p.first_id, p.second_id
""")

_JOURNAL_SUMMARIES = text(f"""
    SELECT j.id, j.title, p.name AS publisher, {active_issns("j.id")} AS issns
    FROM journals j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE j.id = ANY(:ids)
""")

# Revues sans enregistrement, sans publication, sans monographie et sans paiement APC.
_EMPTY_JOURNALS = text(f"""
    SELECT j.id, j.title, p.name AS publisher, {active_issns("j.id")} AS issns
    FROM journals j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE NOT EXISTS (SELECT 1 FROM source_publications s WHERE s.journal_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.journal_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM apc_payments a WHERE a.journal_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM monographs m WHERE m.journal_id = j.id)
    ORDER BY j.id
""")

# Un ISSN déjà présent sans revue tient lieu de la ligne de même valeur des revues supprimées ; leurs autres ISSN
# restent sans revue (`ON DELETE SET NULL`). Les formes de nom partent avec la revue (`ON DELETE CASCADE`).
_DELETE_ISSNS_KNOWN_WITHOUT_JOURNAL = text("""
    DELETE FROM journal_issns i
    WHERE i.journal_id = ANY(:ids)
      AND EXISTS (SELECT 1 FROM journal_issns o WHERE o.issn = i.issn AND o.journal_id IS NULL)
""")
_DELETE_JOURNALS = text("DELETE FROM journals WHERE id = ANY(:ids)")


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


# Une revue posée par son espace de noms porte sa trace dans `raw_metadata.journal_id`.
_DOI_JOURNAL_PAIRS = text("""
    SELECT s.doi, s.journal_id, j.journal_type
    FROM source_publications s
    JOIN journals j ON j.id = s.journal_id
    WHERE s.doi IS NOT NULL AND NOT s.raw_metadata ? 'journal_id'
""")


class PgJournalGatewayQueries(
    JournalFindOrCreateQueries,
    JournalOpenAlexEnrichmentQueries,
    JournalSudocQueries,
    JournalMergeQueries,
    JournalCleanupQueries,
    JournalProceedingsTypingQueries,
    JournalDoiNamespaceQueries,
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
            JournalIssnRow(r.journal_id, r.issn)
            for r in self._conn.execute(
                select(journal_issns.c.journal_id, journal_issns.c.issn)
                .where(
                    journal_issns.c.journal_id.is_not(None),
                    journal_issns.c.status != IssnStatus.MALFORMED,
                )
                .order_by(journal_issns.c.id)
            ).all()
        ]

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
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

    def enrich_journal(
        self,
        journal_id: int,
        *,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: OaModel | None = None,
    ) -> None:
        # L'UPDATE n'est émis que si au moins une colonne NULL recevrait une valeur.
        fillable = (
            (journals.c.publisher_id, publisher_id),
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
                publisher_id=func.coalesce(journals.c.publisher_id, publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, openalex_id),
                # Le littéral est lié au type de la colonne : `coalesce` ne le lui emprunte pas, et
                # `oa_model` est une enum, qu'un paramètre texte ne rejoint pas.
                oa_model=func.coalesce(
                    journals.c.oa_model, literal(oa_model, journals.c.oa_model.type)
                ),
            )
        )

    def add_journal_issns(self, journal_id: int, issns: Sequence[JournalIssn]) -> None:
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

    def find_journals_to_check_in_sudoc(self, also: Sequence[int] = ()) -> list[JournalSudocRow]:
        issns_of = issns_by_journal(self._conn)
        released = set(
            self._conn.execute(
                select(journal_issns.c.issn).where(
                    journal_issns.c.journal_id.is_(None),
                    journal_issns.c.sudoc_checked_at.is_not(None),
                )
            ).scalars()
        )
        documents: dict[int, list[str]] = {}
        for r in self._conn.execute(_DOCUMENT_ISSNS):
            issn = ISSN.try_parse(r.issn)
            own = issns_of.get(r.journal_id, ())
            if issn is None or str(issn) in released or any(i.issn == str(issn) for i in own):
                continue
            values = documents.setdefault(r.journal_id, [])
            if str(issn) not in values:
                values.append(str(issn))
        ids = (
            set(self._conn.execute(_JOURNALS_WITH_UNCHECKED_ISSNS).scalars())
            | set(documents)
            | set(also)
        )
        rows = self._conn.execute(
            select(journals.c.id, journals.c.title, journals.c.journal_type)
            .where(journals.c.id.in_(ids))
            .order_by(journals.c.id)
        ).all()
        return [
            JournalSudocRow(
                r.id,
                r.title,
                issns_of.get(r.id, ()),
                tuple(sorted(documents.get(r.id, ()))),
                JournalType(r.journal_type),
            )
            for r in rows
        ]

    def record_sudoc_check(
        self,
        journal_id: int,
        *,
        issns: Sequence[JournalIssn],
        released: Sequence[JournalIssn],
        checked_at: datetime,
        title: str | None = None,
    ) -> None:
        self._conn.execute(delete(journal_issns).where(journal_issns.c.journal_id == journal_id))
        if issns:
            self._conn.execute(
                journal_issns.insert(),
                [issn_values(row, journal_id=journal_id, checked_at=checked_at) for row in issns],
            )
        for row in released:
            self._conn.execute(
                pg_insert(journal_issns)
                .values(issn_values(row, journal_id=None, checked_at=checked_at))
                .on_conflict_do_update(
                    constraint="uq_journal_issns_issn_journal",
                    set_={"sudoc_checked_at": checked_at},
                )
            )
        if title:
            self._conn.execute(
                update(journals)
                .where(journals.c.id == journal_id)
                .values(title=title, title_normalized=normalize_text(title))
            )
            publisher_id = self._conn.execute(
                select(journals.c.publisher_id).where(journals.c.id == journal_id)
            ).scalar_one()
            self.add_journal_name_form(journal_id, normalize_text(title), publisher_id)

    def find_titles_of_journals_with_issn(self) -> list[JournalTitleTypeRow]:
        rows = self._conn.execute(
            select(journals.c.id, journals.c.title, journals.c.journal_type)
            .where(
                exists().where(
                    journal_issns.c.journal_id == journals.c.id,
                    journal_issns.c.status == IssnStatus.ACTIVE,
                )
            )
            .order_by(journals.c.id)
        )
        return [JournalTitleTypeRow(r.id, r.title, JournalType(r.journal_type)) for r in rows]

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
                exists()
                .where(
                    journal_issns.c.journal_id == journals.c.id,
                    journal_issns.c.status == IssnStatus.ACTIVE,
                )
                .label("has_issn"),
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

    def find_journals_sharing_an_inactive_issn(self) -> list[JournalMergeGroup]:
        return [
            JournalMergeGroup(r.issn, tuple(r.ids))
            for r in self._conn.execute(_JOURNALS_SHARING_AN_INACTIVE_ISSN).all()
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
        return {r.id: JournalSummary(r.id, r.title, r.publisher, tuple(r.issns)) for r in rows}

    # ── nettoyage ──────────────────────────────────────────────────

    def delete_empty_journals(self) -> list[JournalSummary]:
        empty = [
            JournalSummary(r.id, r.title, r.publisher, tuple(r.issns))
            for r in self._conn.execute(_EMPTY_JOURNALS).all()
        ]
        ids = [j.id for j in empty]
        self._conn.execute(_DELETE_ISSNS_KNOWN_WITHOUT_JOURNAL, {"ids": ids})
        self._conn.execute(_DELETE_JOURNALS, {"ids": ids})
        return empty

    def find_journals_sharing_active_issn(self) -> list[JournalIssnGroup]:
        return [
            JournalIssnGroup(
                r.issn, tuple(JournalTitleRow(i, t) for i, t in zip(r.ids, r.titles, strict=True))
            )
            for r in self._conn.execute(_JOURNALS_SHARING_ACTIVE_ISSN).all()
        ]

    def create_journal(
        self,
        *,
        title: str,
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

    def set_journal_type_if_unknown(self, journal_id: int, journal_type: JournalType) -> None:
        self._conn.execute(
            update(journals)
            .where(journals.c.id == journal_id, journals.c.journal_type == JournalType.UNKNOWN)
            .values(journal_type=journal_type)
        )

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        self._conn.execute(
            update(journals).where(journals.c.id == journal_id).values(journal_type=journal_type)
        )

    # ── Espaces de noms DOI ────────────────────────────────────────

    def find_doi_journal_pairs(self) -> list[DoiJournalRow]:
        return [
            DoiJournalRow(r.doi, r.journal_id, JournalType(r.journal_type))
            for r in self._conn.execute(_DOI_JOURNAL_PAIRS)
        ]

    def store_doi_namespaces(self, namespaces: Sequence[DoiNamespace]) -> None:
        self._conn.execute(journal_doi_namespaces.delete())
        if namespaces:
            self._conn.execute(journal_doi_namespaces.insert(), [ns._asdict() for ns in namespaces])

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
