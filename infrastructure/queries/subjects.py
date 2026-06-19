"""Query service : SQL pour la table `subjects` et la liaison
`publication_subjects`.

Consommé par la phase `application/pipeline/subjects/` (fonctions sync)
et par les routes API `/api/subjects/*` (classe `PgSubjectsAdminQueries`,
implémentation du port `application.ports.subjects_queries`).
Voir docs/chantiers/sujets-mots-cles.md.
"""

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.api.subjects_queries import (
    SubjectListItem,
    SubjectNeighborOut,
    SubjectsAdminQueries,
)
from application.ports.pipeline.subjects import OntologyEntry, SubjectsQueries
from domain.subjects.subject import normalize_label

# Le ON CONFLICT fusionne par ontologie : pour chaque clé présente dans l'un
# OU l'autre des dicts, on construit un objet `{codes, level, parent}` agrégé.
# `codes` = union des listes ; `level` et `parent` = premier non-null
# (existant prioritaire).
_UPSERT_SUBJECT_SQL = text(
    """
    INSERT INTO subjects (label, language, ontologies)
    VALUES (:label, :language, :ontologies)
    ON CONFLICT (lower(label)) DO UPDATE SET
        ontologies = COALESCE(
            (
                SELECT jsonb_object_agg(k, body)
                FROM (
                    SELECT
                        k,
                        jsonb_build_object(
                            'codes',
                            COALESCE(
                                (
                                    SELECT jsonb_agg(DISTINCT code)
                                    FROM (
                                        SELECT jsonb_array_elements_text(
                                            COALESCE(subjects.ontologies->k->'codes', '[]'::jsonb)
                                        ) AS code
                                        UNION
                                        SELECT jsonb_array_elements_text(
                                            COALESCE(EXCLUDED.ontologies->k->'codes', '[]'::jsonb)
                                        )
                                    ) merged_codes
                                ),
                                '[]'::jsonb
                            ),
                            'level',
                            COALESCE(
                                subjects.ontologies->k->'level',
                                EXCLUDED.ontologies->k->'level'
                            ),
                            'parent',
                            COALESCE(
                                subjects.ontologies->k->'parent',
                                EXCLUDED.ontologies->k->'parent'
                            )
                        ) AS body
                    FROM (
                        SELECT key AS k FROM jsonb_each(subjects.ontologies)
                        UNION
                        SELECT key AS k FROM jsonb_each(EXCLUDED.ontologies)
                    ) keys
                ) merged
            ),
            '{}'::jsonb
        ),
        language = COALESCE(subjects.language, EXCLUDED.language)
    RETURNING id
    """
).bindparams(bindparam("ontologies", type_=JSONB))


def upsert_subject(
    conn: Connection,
    *,
    label: str,
    language: str | None = None,
    ontologies: dict[str, OntologyEntry] | None = None,
) -> int:
    """UPSERT d'un sujet identifié par `lower(label)`. Retourne l'id.

    `ontologies` : dict `{ontology_name: {"codes": [...], "level": int|null,
    "parent": str|null}}`. Vide ou None pour un libre. À l'`ON CONFLICT` :
    pour chaque clé d'ontologie commune, on fusionne les `codes` (union sans
    doublon) ; on garde la première valeur non-null vue pour `level` et
    `parent` (côté existant prioritaire).
    """
    return conn.execute(
        _UPSERT_SUBJECT_SQL,
        {"label": normalize_label(label), "language": language, "ontologies": ontologies or {}},
    ).scalar_one()


def link_publication_subject(
    conn: Connection,
    *,
    publication_id: int,
    subject_id: int,
    source: str,
    score: float | None = None,
) -> None:
    """Crée le lien publication↔subject pour une source donnée.

    PK `(publication_id, subject_id, source)` : un même sujet annoté par
    deux sources différentes donne deux lignes ; un même sujet annoté
    deux fois par la même source écrase le score précédent.
    """
    conn.execute(
        text(
            """
            INSERT INTO publication_subjects (publication_id, subject_id, source, score)
            VALUES (:pid, :sid, :src, :score)
            ON CONFLICT (publication_id, subject_id, source)
            DO UPDATE SET score = EXCLUDED.score
            """
        ),
        {"pid": publication_id, "sid": subject_id, "src": source, "score": score},
    )


def link_publication_subjects_bulk(
    conn: Connection,
    *,
    source: str,
    rows: list[tuple[int, int, float | None]],
) -> int:
    """Bulk INSERT des liens publication↔subject pour une source.

    `rows` : liste `(publication_id, subject_id, score)`. La source est
    constante pour le batch. Idempotent grâce au `ON CONFLICT DO UPDATE`.
    Avec la fusion par label, plusieurs annotations source peuvent pointer
    vers le même `subject_id` pour une même publication ; on dédoublonne
    `(pub_id, subject_id)` côté Python avant l'INSERT pour ne pas envoyer
    de lignes redondantes (lourd à inutile).

    Retourne le nombre de lignes envoyées.
    """
    if not rows:
        return 0
    seen: set[tuple[int, int]] = set()
    deduped: list[dict[str, Any]] = []
    for pub_id, sid, score in rows:
        key = (pub_id, sid)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"pid": pub_id, "sid": sid, "src": source, "score": score})
    conn.execute(
        text(
            """
            INSERT INTO publication_subjects (publication_id, subject_id, source, score)
            VALUES (:pid, :sid, :src, :score)
            ON CONFLICT (publication_id, subject_id, source)
            DO UPDATE SET score = EXCLUDED.score
            """
        ),
        deduped,
    )
    return len(deduped)


def clear_publication_subjects(
    conn: Connection,
    *,
    publication_id: int,
    source: str,
) -> int:
    """Supprime les liens (non rejetés) d'une publication pour une source.
    Retourne le nombre de lignes supprimées."""
    return conn.execute(
        text(
            "DELETE FROM publication_subjects "
            "WHERE publication_id = :pid AND source = :src AND NOT rejected"
        ),
        {"pid": publication_id, "src": source},
    ).rowcount


def clear_publication_subjects_for_pubs(conn: Connection, *, publication_ids: list[int]) -> int:
    """`DELETE` des liens (non rejetés) des publications données, toutes sources.

    Préserve les liens manuellement rejetés (colonne `rejected`). Appelé par la
    phase `subjects` avant ré-ingestion des publications dont le contenu canonique
    a changé.
    """
    if not publication_ids:
        return 0
    return conn.execute(
        text("DELETE FROM publication_subjects WHERE publication_id = ANY(:ids) AND NOT rejected"),
        {"ids": publication_ids},
    ).rowcount


def select_publications_to_reingest(conn: Connection) -> list[int]:
    """Publications dont les sujets sont à (ré)ingérer : contenu canonique modifié
    depuis la dernière ingestion de leurs liens, ou jamais ingérées.

    Incrémental sans colonne dédiée : la référence « dernière ingestion » est
    `max(publication_subjects.created_at)` par publication (le `created_at` est
    posé à l'INSERT de chaque lien) ; le signal de changement est
    `publications.updated_at` (bumpé par `refresh_from_sources` quand une source
    change — conditionnel, donc propre). Les pubs sans aucun lien (jamais
    ingérées, ~1 %) sont incluses via le `IS NULL`.
    """
    return [
        r.id
        for r in conn.execute(
            text(
                """
                SELECT p.id
                FROM publications p
                LEFT JOIN (
                    SELECT publication_id, max(created_at) AS last_ingest
                    FROM publication_subjects
                    GROUP BY publication_id
                ) li ON li.publication_id = p.id
                WHERE li.last_ingest IS NULL OR p.updated_at > li.last_ingest
                """
            )
        ).all()
    ]


def select_source_publications_for_pubs(
    conn: Connection, *, publication_ids: list[int]
) -> list[Any]:
    """`source_publications` (id, publication_id, source, keywords, topics) des
    publications données — la matière première par-source pour ré-ingérer leurs
    sujets en conservant l'attribution `publication_subjects.source`.
    """
    if not publication_ids:
        return []
    return list(
        conn.execute(
            text(
                """
                SELECT id, publication_id, source, keywords, topics
                FROM source_publications
                WHERE publication_id = ANY(:ids)
                ORDER BY publication_id
                """
            ),
            {"ids": publication_ids},
        ).all()
    )


def purge_orphan_subjects(conn: Connection) -> int:
    """Supprime les sujets sans aucun lien `publication_subjects` (tous statuts).

    Les `subjects` ne sont créés que par l'ingestion et ne sont jamais purgés au
    fil de l'eau ; un sujet sans lien est un orphelin (ex. keyword d'une
    publication purgée — la purge des publications cascade les liens mais pas le
    référentiel, ou keyword retiré d'une source). On vise **zéro lien tous
    statuts** (et non `usage_count = 0`) pour préserver un sujet portant un lien
    rejeté (curation). Retourne le nombre supprimé.
    """
    return conn.execute(
        text(
            "DELETE FROM subjects s WHERE NOT EXISTS "
            "(SELECT 1 FROM publication_subjects ps WHERE ps.subject_id = s.id)"
        )
    ).rowcount


# ── Co-occurrences ───────────────────────────────────────────────


def recompute_usage_counts(conn: Connection) -> int:
    """Recalcule `subjects.usage_count` = nb publications distinctes par sujet."""
    n_reset = conn.execute(
        text("UPDATE subjects SET usage_count = 0 WHERE usage_count <> 0")
    ).rowcount
    n_updated = conn.execute(
        text(
            """
            UPDATE subjects s
            SET usage_count = c.n
            FROM (
                SELECT subject_id, COUNT(DISTINCT publication_id) AS n
                FROM publication_subjects
                WHERE NOT rejected
                GROUP BY subject_id
            ) c
            WHERE s.id = c.subject_id
            """
        )
    ).rowcount
    return n_reset + n_updated


def refresh_cooccurrences(conn: Connection) -> int:
    """Rafraîchit la matview `subject_cooccurrences` depuis `publication_subjects`.

    Seuil `count >= 2` figé dans la définition de la matview. Retourne
    le nombre de paires dans la vue après refresh.
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW subject_cooccurrences"))
    return conn.execute(text("SELECT COUNT(*) FROM subject_cooccurrences")).scalar_one()


# ── Lectures (consommées par les routes API) ─────────────────────


class PgSubjectsAdminQueries(SubjectsAdminQueries):
    """Adapter SA pour `application.ports.subjects_queries.SubjectsAdminQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_subjects(
        self, *, q: str | None, limit: int, offset: int, min_count: int
    ) -> list[SubjectListItem]:
        binds: dict[str, Any] = {"min_count": min_count, "lim": limit, "off": offset}
        where = "usage_count >= :min_count"
        if q:
            where += " AND unaccent(label) ILIKE unaccent(:q)"
            binds["q"] = f"%{q}%"
        rows = self._conn.execute(
            text(f"""
                SELECT id, label, language, ontologies, usage_count
                FROM subjects
                WHERE {where}
                ORDER BY usage_count DESC, lower(label)
                LIMIT :lim OFFSET :off
            """),
            binds,
        ).all()
        return [
            SubjectListItem(
                id=r.id,
                label=r.label,
                language=r.language,
                ontologies=r.ontologies or {},
                usage_count=r.usage_count,
            )
            for r in rows
        ]

    def count_subjects(self, *, q: str | None, min_count: int) -> int:
        binds: dict[str, Any] = {"min_count": min_count}
        where = "usage_count >= :min_count"
        if q:
            where += " AND unaccent(label) ILIKE unaccent(:q)"
            binds["q"] = f"%{q}%"
        row = self._conn.execute(
            text(f"SELECT COUNT(*) AS n FROM subjects WHERE {where}"),
            binds,
        ).one()
        return row.n

    def get_subject(self, subject_id: int) -> SubjectListItem | None:
        row = self._conn.execute(
            text("""
                SELECT id, label, language, ontologies, usage_count
                FROM subjects
                WHERE id = :id
            """),
            {"id": subject_id},
        ).one_or_none()
        if row is None:
            return None
        return SubjectListItem(
            id=row.id,
            label=row.label,
            language=row.language,
            ontologies=row.ontologies or {},
            usage_count=row.usage_count,
        )

    def get_subject_neighbors(
        self, subject_id: int, *, limit: int, min_count: int
    ) -> list[SubjectNeighborOut]:
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.label, s.ontologies, s.usage_count,
                       c.n AS cooccurrence_count
                FROM (
                    SELECT subject_b_id AS other, count AS n
                    FROM subject_cooccurrences WHERE subject_a_id = :sid
                    UNION ALL
                    SELECT subject_a_id AS other, count AS n
                    FROM subject_cooccurrences WHERE subject_b_id = :sid
                ) c
                JOIN subjects s ON s.id = c.other
                WHERE c.n >= :min_count
                ORDER BY c.n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"sid": subject_id, "min_count": min_count, "lim": limit},
        ).all()
        return [
            SubjectNeighborOut(
                id=r.id,
                label=r.label,
                ontologies=r.ontologies or {},
                usage_count=r.usage_count,
                cooccurrence_count=r.cooccurrence_count,
            )
            for r in rows
        ]


class PgSubjectsQueries(SubjectsQueries):
    """Adapter PostgreSQL implémentant `application.ports.subjects.SubjectsQueries`."""

    def upsert_subject(
        self,
        conn: Connection,
        *,
        label: str,
        language: str | None = None,
        ontologies: dict[str, OntologyEntry] | None = None,
    ) -> int:
        return upsert_subject(
            conn,
            label=label,
            language=language,
            ontologies=ontologies,
        )

    def link_publication_subjects_bulk(
        self,
        conn: Connection,
        *,
        source: str,
        rows: list[tuple[int, int, float | None]],
    ) -> int:
        return link_publication_subjects_bulk(conn, source=source, rows=rows)

    def clear_publication_subjects_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> int:
        return clear_publication_subjects_for_pubs(conn, publication_ids=publication_ids)

    def select_publications_to_reingest(self, conn: Connection) -> list[int]:
        return select_publications_to_reingest(conn)

    def select_source_publications_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> list[Any]:
        return select_source_publications_for_pubs(conn, publication_ids=publication_ids)

    def purge_orphan_subjects(self, conn: Connection) -> int:
        return purge_orphan_subjects(conn)

    def recompute_usage_counts(self, conn: Connection) -> int:
        return recompute_usage_counts(conn)

    def refresh_cooccurrences(self, conn: Connection) -> int:
        return refresh_cooccurrences(conn)
