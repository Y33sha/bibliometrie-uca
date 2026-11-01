"""Lectures des sujets servies par les routes `/api/subjects/*`, et sujets principaux des tableaux de bord des personnes, laboratoires, revues et éditeurs.

Les écritures du référentiel appartiennent à la phase `subjects` (`pipeline/transformation/publications/subjects/subject_store.py`).
"""

from collections import defaultdict
from collections.abc import Iterator, Mapping

from sqlalchemy import Connection, Row, text

from domain.normalize import normalize_text
from domain.subjects.subject import VOCABULARY_LABELS
from infrastructure.read_models.csv_export import csv_chunks, fetch_export_rows
from infrastructure.read_models.subjects.models import (
    SubjectChildOut,
    SubjectDetailResponse,
    SubjectFrequency,
    SubjectLabelRef,
    SubjectListItem,
    SubjectListResponse,
    SubjectNeighborLink,
    SubjectNeighborOut,
    SubjectSort,
    VocabularySubjectOut,
)

# Un sujet dont l'usage global dépasse ce seuil est trop générique pour un nuage de mots : « research article » ou « science » arrivent en tête partout, et masquent ce qui distingue le contexte affiché.
GENERIC_SUBJECT_MAX_USAGE = 5000

_SORT_MAP: dict[SubjectSort, str] = {
    "label_asc": "sl.label_normalized ASC",
    "label_desc": "sl.label_normalized DESC",
    "publications_asc": "sl.usage_count ASC, sl.label_normalized",
    "publications_desc": "sl.usage_count DESC, sl.label_normalized",
}

# Vocabulaires de chaque libellé normalisé, dans l'ordre de l'enum.
_VOCABULARIES_SQL = """
    SELECT label_normalized, array_agg(DISTINCT vocabulary ORDER BY vocabulary)::text[] AS vocabularies
    FROM subjects
    WHERE usage_count > 0
    GROUP BY label_normalized
"""

_ANCESTORS_SQL = text("""
    WITH RECURSIVE chain AS (
        SELECT id AS subject_id, parent_id AS ancestor_id
        FROM subjects
        WHERE id = ANY(:ids) AND parent_id IS NOT NULL
        UNION ALL
        SELECT c.subject_id, a.parent_id
        FROM chain c
        JOIN subjects a ON a.id = c.ancestor_id
        WHERE a.parent_id IS NOT NULL
    )
    SELECT c.subject_id, a.label_normalized, a.label
    FROM chain c
    JOIN subjects a ON a.id = c.ancestor_id
    ORDER BY c.subject_id, a.level
""")

_CHILDREN_SQL = text("""
    SELECT parent_id, label_normalized, label, usage_count
    FROM subjects
    WHERE parent_id = ANY(:ids) AND usage_count > 0
    ORDER BY usage_count DESC, label_normalized
""")

_NEIGHBORS_SQL = text("""
    SELECT sl.label_normalized, sl.label, sl.usage_count, c.n AS cooccurrence_count
    FROM (
        SELECT label_b AS other, count AS n FROM subject_cooccurrences WHERE label_a = :key
        UNION ALL
        SELECT label_a AS other, count AS n FROM subject_cooccurrences WHERE label_b = :key
    ) c
    JOIN subject_labels sl ON sl.label_normalized = c.other
    WHERE c.n >= :min_count
    ORDER BY c.n DESC, sl.label_normalized
    LIMIT :lim
""")

_NEIGHBOR_LINKS_SQL = text("""
    SELECT label_a, label_b, count AS cooccurrence_count
    FROM subject_cooccurrences
    WHERE label_a = ANY(:labels) AND label_b = ANY(:labels) AND count >= :min_count
""")


def _search_clause(search: str | None) -> tuple[str, dict[str, object]]:
    """Renvoie la clause de recherche de l'annuaire des sujets sur le libellé normalisé, avec ses paramètres. La liste et son total la partagent."""
    normalized = normalize_text(search or "")
    if not normalized:
        return "TRUE", {}
    return "sl.label_normalized LIKE :search", {"search": f"%{normalized}%"}


def _list_sql(where: str, sort: SubjectSort) -> str:
    """Renvoie la requête triée de la liste des sujets, sans pagination."""
    return f"""
        SELECT sl.label_normalized, sl.label, sl.usage_count, v.vocabularies
        FROM subject_labels sl
        JOIN ({_VOCABULARIES_SQL}) v ON v.label_normalized = sl.label_normalized
        WHERE {where}
        ORDER BY {_SORT_MAP[sort]}
    """


def _subject_list_item(row: Row[tuple[object, ...]]) -> SubjectListItem:
    return SubjectListItem(
        label_normalized=row.label_normalized,
        label=row.label,
        vocabularies=row.vocabularies,
        usage_count=row.usage_count,
    )


def entity_subjects(
    conn: Connection, entity_predicate: str, params: Mapping[str, object], *, limit: int
) -> list[SubjectFrequency]:
    """Renvoie les sujets les plus fréquents des publications retenues par `entity_predicate` (alias `p`), hors sujets génériques.

    Chaque page d'entité (revue, éditeur, laboratoire, personne) passe son propre prédicat et ses paramètres.
    """
    rows = conn.execute(
        text(f"""
            SELECT sl.label_normalized, sl.label, COUNT(DISTINCT p.id) AS n
            FROM publication_subjects ps
            JOIN publications p ON p.id = ps.publication_id
            JOIN subjects s ON s.id = ps.subject_id
            JOIN subject_labels sl ON sl.label_normalized = s.label_normalized
            WHERE {entity_predicate}
              AND sl.usage_count <= {GENERIC_SUBJECT_MAX_USAGE}
            GROUP BY sl.label_normalized, sl.label
            ORDER BY n DESC, sl.label_normalized
            LIMIT :lim
        """),
        {**params, "lim": limit},
    ).all()
    return [
        SubjectFrequency(label_normalized=r.label_normalized, label=r.label, count=r.n)
        for r in rows
    ]


class SubjectsQueries:
    """Lectures sur les sujets."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_subjects(
        self, *, search: str | None, sort: SubjectSort, page: int, per_page: int
    ) -> SubjectListResponse:
        where, binds = _search_clause(search)
        rows = self._conn.execute(
            text(f"{_list_sql(where, sort)} LIMIT :lim OFFSET :off"),
            {**binds, "lim": per_page, "off": (page - 1) * per_page},
        ).all()
        items = [_subject_list_item(r) for r in rows]
        total = (
            self._conn.execute(
                text(f"SELECT COUNT(*) AS n FROM subject_labels sl WHERE {where}"),
                binds,
            )
            .one()
            .n
        )
        return SubjectListResponse(items=items, total=total, page=page, per_page=per_page)

    def export_subjects_csv(self, *, search: str | None, sort: SubjectSort) -> Iterator[str]:
        """Renvoie l'export CSV de la liste des sujets, aux filtres et au tri de la liste.

        La requête s'exécute à l'appel. Le parcours qui suit lit des lignes en mémoire.
        """
        where, binds = _search_clause(search)
        rows, truncated = fetch_export_rows(
            self._conn, _list_sql(where, sort), binds, name="sujets"
        )
        return csv_chunks(
            ["Libellé", "Vocabulaires", "Occurrences"],
            (
                [
                    r.label,
                    ", ".join(VOCABULARY_LABELS[v] for v in r.vocabularies),
                    r.usage_count,
                ]
                for r in rows
            ),
            truncated=truncated,
        )

    def get_subject_detail(
        self, label_normalized: str, *, neighbors_limit: int, min_cooccurrence_count: int
    ) -> SubjectDetailResponse | None:
        """Renvoie le détail du sujet de libellé normalisé `label_normalized`, ou `None` pour un libellé sans publication."""
        row = self._conn.execute(
            text(_list_sql("sl.label_normalized = :key", "publications_desc")),
            {"key": label_normalized},
        ).one_or_none()
        if row is None:
            return None
        neighbor_rows = self._conn.execute(
            _NEIGHBORS_SQL,
            {"key": label_normalized, "min_count": min_cooccurrence_count, "lim": neighbors_limit},
        ).all()
        neighbors = [
            SubjectNeighborOut(
                label_normalized=r.label_normalized,
                label=r.label,
                usage_count=r.usage_count,
                cooccurrence_count=r.cooccurrence_count,
            )
            for r in neighbor_rows
        ]
        link_rows = self._conn.execute(
            _NEIGHBOR_LINKS_SQL,
            {
                "labels": [n.label_normalized for n in neighbors],
                "min_count": min_cooccurrence_count,
            },
        ).all()
        return SubjectDetailResponse(
            subject=_subject_list_item(row),
            vocabulary_subjects=self._vocabulary_subjects(label_normalized),
            neighbors=neighbors,
            neighbor_links=[
                SubjectNeighborLink(
                    label_a=r.label_a, label_b=r.label_b, cooccurrence_count=r.cooccurrence_count
                )
                for r in link_rows
            ],
        )

    def _vocabulary_subjects(self, label_normalized: str) -> list[VocabularySubjectOut]:
        """Renvoie les sujets de vocabulaire du libellé normalisé, avec leurs ancêtres et leurs enfants."""
        rows = self._conn.execute(
            text("""
                SELECT id, vocabulary::text AS vocabulary, code, level, usage_count
                FROM subjects
                WHERE label_normalized = :key AND usage_count > 0
                ORDER BY vocabulary, usage_count DESC, code
            """),
            {"key": label_normalized},
        ).all()
        ids = [r.id for r in rows]
        ancestors: defaultdict[int, list[SubjectLabelRef]] = defaultdict(list)
        for a in self._conn.execute(_ANCESTORS_SQL, {"ids": ids}):
            ancestors[a.subject_id].append(
                SubjectLabelRef(label_normalized=a.label_normalized, label=a.label)
            )
        children: defaultdict[int, list[SubjectChildOut]] = defaultdict(list)
        for c in self._conn.execute(_CHILDREN_SQL, {"ids": ids}):
            children[c.parent_id].append(
                SubjectChildOut(
                    label_normalized=c.label_normalized, label=c.label, usage_count=c.usage_count
                )
            )
        return [
            VocabularySubjectOut(
                vocabulary=r.vocabulary,
                code=r.code,
                level=r.level,
                usage_count=r.usage_count,
                ancestors=ancestors[r.id],
                children=children[r.id],
            )
            for r in rows
        ]


__all__ = ["SubjectsQueries", "entity_subjects"]
