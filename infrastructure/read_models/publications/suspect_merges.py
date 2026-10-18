"""File des fusions suspectes : publications dont les notices ont des listes d'auteurs qui ne se recouvrent pas, lues dans `publication_author_alignment`."""

from sqlalchemy import Connection, text

from application.ports.read_models.publications_queries import (
    SuspectMergeNoticeOut,
    SuspectMergeOut,
    SuspectMergesResponse,
)
from domain.publications.authorship_roles import AuthorshipRole

# Moins de la moitié des signatures d'auteur sont dans un groupe dont un membre est lié par la règle (nom, identifiant, ordre).
_SUSPECT = "2 * pa.rule_aligned_signatures < pa.signatures"

_NOTICES_SQL = text(f"""
    WITH members AS (
        SELECT g.publication_id, gs.source_publication_id,
               count(*) OVER (PARTITION BY gs.group_id) AS group_size,
               bool_or(gs.method IN ('name', 'identifier', 'order'))
                   OVER (PARTITION BY gs.group_id) AS rule_linked
        FROM source_authorship_groups g
        JOIN grouped_source_authorships gs ON gs.group_id = g.id
        JOIN source_authorships sa ON sa.id = gs.source_authorship_id
        WHERE g.publication_id = ANY(:publications)
          AND (sa.roles IS NULL OR '{AuthorshipRole.AUTHOR.value}' = ANY(sa.roles))
    )
    SELECT m.publication_id, sp.source::text AS source, sp.source_id,
           count(*) AS signatures, count(*) FILTER (WHERE m.rule_linked) AS rule_aligned_signatures,
           count(*) FILTER (WHERE m.group_size = 1) AS lone_signatures
    FROM members m
    JOIN source_publications sp ON sp.id = m.source_publication_id
    GROUP BY m.publication_id, sp.source, sp.source_id
    ORDER BY m.publication_id, count(*) DESC, sp.source, sp.source_id
""")  # noqa: S608


def suspect_merges_count(conn: Connection) -> int:
    """Nombre de publications de la file (badge de l'onglet)."""
    return int(
        conn.execute(
            text(f"SELECT count(*) FROM publication_author_alignment pa WHERE {_SUSPECT}")  # noqa: S608
        ).scalar_one()
    )


def suspect_merges(conn: Connection, *, page: int, per_page: int) -> SuspectMergesResponse:
    """Publications de la file, la plus faible part de signatures d'auteur alignées par la règle d'abord, avec le décompte de chaque notice."""
    total = suspect_merges_count(conn)
    rows = conn.execute(
        text(f"""
            SELECT pa.publication_id, p.title, p.pub_year, p.doc_type::text AS doc_type,
                   pa.signatures, pa.rule_aligned_signatures, pa.lone_signatures,
                   pa.model_signatures, pa.min_margin
            FROM publication_author_alignment pa
            JOIN publications p ON p.id = pa.publication_id
            WHERE {_SUSPECT}
            ORDER BY pa.rule_aligned_signatures::float / pa.signatures, pa.signatures DESC, pa.publication_id
            LIMIT :limit OFFSET :offset
        """),  # noqa: S608
        {"limit": per_page, "offset": (page - 1) * per_page},
    ).all()
    notices: dict[int, list[SuspectMergeNoticeOut]] = {}
    for n in conn.execute(_NOTICES_SQL, {"publications": [r.publication_id for r in rows]}):
        notices.setdefault(n.publication_id, []).append(
            SuspectMergeNoticeOut(
                source=n.source,
                source_id=n.source_id,
                signatures=n.signatures,
                rule_aligned_signatures=n.rule_aligned_signatures,
                lone_signatures=n.lone_signatures,
            )
        )
    return SuspectMergesResponse(
        total=total,
        page=page,
        per_page=per_page,
        publications=[
            SuspectMergeOut(
                publication_id=r.publication_id,
                title=r.title,
                pub_year=r.pub_year,
                doc_type=r.doc_type,
                signatures=r.signatures,
                rule_aligned_signatures=r.rule_aligned_signatures,
                lone_signatures=r.lone_signatures,
                model_signatures=r.model_signatures,
                min_margin=r.min_margin,
                notices=notices.get(r.publication_id, []),
            )
            for r in rows
        ],
    )
