"""Query service : SQL pour la table `subjects` et la liaison
`publication_subjects`.

Consommé par la phase `application/pipeline/subjects/` et par les
routes API `/api/subjects/*`. Voir docs/chantiers/sujets-mots-cles.md.

Les fonctions sync alimentent le pipeline ; les fonctions `*_async`
sont pour les routes FastAPI.
"""

from typing import Any

from psycopg.types.json import Json

from domain.subject import normalize_label


def upsert_subject(
    cur: Any,
    *,
    label: str,
    language: str | None = None,
    ontologies: dict[str, dict[str, Any]] | None = None,
) -> int:
    """UPSERT d'un sujet identifié par `lower(label)`. Retourne l'id.

    `ontologies` : dict `{ontology_name: {"codes": [...], "level": int|null,
    "parent": str|null}}`. Vide ou None pour un libre. À l'`ON CONFLICT` :
    pour chaque clé d'ontologie commune, on fusionne les `codes` (union sans
    doublon) ; on garde la première valeur non-null vue pour `level` et
    `parent` (côté existant prioritaire).
    """
    normalized = normalize_label(label)
    onto = ontologies or {}
    cur.execute(
        """
        INSERT INTO subjects (label, language, ontologies)
        VALUES (%s, %s, %s)
        ON CONFLICT (lower(label)) DO UPDATE SET
            -- Fusion par ontologie : pour chaque clé présente dans l'un OU
            -- l'autre des dicts, on construit un objet `{codes, level,
            -- parent}` agrégé. `codes` = union des listes ; `level` et
            -- `parent` = premier non-null (existant prioritaire).
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
        """,
        (normalized, language, Json(onto)),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def link_publication_subject(
    cur: Any,
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
    cur.execute(
        """
        INSERT INTO publication_subjects (publication_id, subject_id, source, score)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (publication_id, subject_id, source)
        DO UPDATE SET score = EXCLUDED.score
        """,
        (publication_id, subject_id, source, score),
    )


def link_publication_subjects_bulk(
    cur: Any,
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
    deduped: list[tuple[int, int, str, float | None]] = []
    for pub_id, sid, score in rows:
        key = (pub_id, sid)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((pub_id, sid, source, score))
    cur.executemany(
        """
        INSERT INTO publication_subjects (publication_id, subject_id, source, score)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (publication_id, subject_id, source)
        DO UPDATE SET score = EXCLUDED.score
        """,
        deduped,
    )
    return len(deduped)


def clear_publication_subjects(
    cur: Any,
    *,
    publication_id: int,
    source: str,
) -> int:
    """Supprime tous les liens d'une publication pour une source.
    Retourne le nombre de lignes supprimées."""
    cur.execute(
        """
        DELETE FROM publication_subjects
        WHERE publication_id = %s AND source = %s
        """,
        (publication_id, source),
    )
    return cur.rowcount


def clear_links_for_source(cur: Any, *, source: str) -> int:
    """`DELETE FROM publication_subjects WHERE source = X`. Retourne le rowcount."""
    cur.execute("DELETE FROM publication_subjects WHERE source = %s", (source,))
    return cur.rowcount


def select_source_publications_with_subjects(cur: Any, *, source: str) -> list[Any]:
    """Lit les `source_publications` rattachées à une publication canonique."""
    cur.execute(
        """
        SELECT publication_id, keywords, topics
        FROM source_publications
        WHERE source = %s AND publication_id IS NOT NULL
        """,
        (source,),
    )
    return cur.fetchall()


# ── Co-occurrences ───────────────────────────────────────────────


def recompute_usage_counts(cur: Any) -> int:
    """Recalcule `subjects.usage_count` = nb publications distinctes par sujet."""
    cur.execute("UPDATE subjects SET usage_count = 0 WHERE usage_count <> 0")
    n_reset = cur.rowcount
    cur.execute(
        """
        UPDATE subjects s
        SET usage_count = c.n
        FROM (
            SELECT subject_id, COUNT(DISTINCT publication_id) AS n
            FROM publication_subjects
            GROUP BY subject_id
        ) c
        WHERE s.id = c.subject_id
        """
    )
    return n_reset + cur.rowcount


def recompute_cooccurrences(cur: Any, *, min_count: int = 2) -> int:
    """Recalcule `subject_cooccurrences` depuis `publication_subjects`.

    TRUNCATE puis INSERT en bloc, filtré par count >= min_count. Retourne
    le nombre de paires insérées.
    """
    cur.execute("TRUNCATE subject_cooccurrences")
    cur.execute(
        """
        INSERT INTO subject_cooccurrences (subject_a_id, subject_b_id, count)
        SELECT
            ps1.subject_id AS a_id,
            ps2.subject_id AS b_id,
            COUNT(DISTINCT ps1.publication_id) AS n
        FROM publication_subjects ps1
        JOIN publication_subjects ps2
          ON ps1.publication_id = ps2.publication_id
         AND ps1.subject_id < ps2.subject_id
        GROUP BY ps1.subject_id, ps2.subject_id
        HAVING COUNT(DISTINCT ps1.publication_id) >= %s
        """,
        (min_count,),
    )
    return cur.rowcount


# ── Lectures async (consommées par les routes API) ───────────────


async def list_subjects_async(
    cur: Any,
    *,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    min_count: int = 1,
) -> list[dict[str, Any]]:
    """Liste paginée de sujets, ordonnée par `usage_count` desc puis label."""
    where_clauses = ["usage_count >= %s"]
    params: list[Any] = [min_count]
    if q:
        where_clauses.append("lower(label) LIKE %s")
        params.append(f"%{q.lower()}%")
    where_sql = " AND ".join(where_clauses)
    await cur.execute(
        f"""
        SELECT id, label, language, ontologies, usage_count
        FROM subjects
        WHERE {where_sql}
        ORDER BY usage_count DESC, lower(label)
        LIMIT %s OFFSET %s
        """,
        [*params, limit, offset],
    )
    return [dict(r) for r in await cur.fetchall()]


async def count_subjects_async(
    cur: Any,
    *,
    q: str | None = None,
    min_count: int = 1,
) -> int:
    """Cardinalité totale (pour la pagination)."""
    where_clauses = ["usage_count >= %s"]
    params: list[Any] = [min_count]
    if q:
        where_clauses.append("lower(label) LIKE %s")
        params.append(f"%{q.lower()}%")
    where_sql = " AND ".join(where_clauses)
    await cur.execute(f"SELECT COUNT(*) AS n FROM subjects WHERE {where_sql}", params)
    row = await cur.fetchone()
    return row["n"] if isinstance(row, dict) else row[0]


async def get_subject_async(cur: Any, subject_id: int) -> dict[str, Any] | None:
    """Détail d'un sujet (None si absent)."""
    await cur.execute(
        """
        SELECT id, label, language, ontologies, usage_count
        FROM subjects
        WHERE id = %s
        """,
        (subject_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_subject_neighbors_async(
    cur: Any,
    subject_id: int,
    *,
    limit: int = 20,
    min_count: int = 2,
) -> list[dict[str, Any]]:
    """Top voisins par count de co-occurrence, agrégé bidirectionnellement."""
    await cur.execute(
        """
        SELECT s.id, s.label, s.ontologies, s.usage_count, c.n AS cooccurrence_count
        FROM (
            SELECT subject_b_id AS other, count AS n
            FROM subject_cooccurrences WHERE subject_a_id = %s
            UNION ALL
            SELECT subject_a_id AS other, count AS n
            FROM subject_cooccurrences WHERE subject_b_id = %s
        ) c
        JOIN subjects s ON s.id = c.other
        WHERE c.n >= %s
        ORDER BY c.n DESC, lower(s.label)
        LIMIT %s
        """,
        (subject_id, subject_id, min_count, limit),
    )
    return [dict(r) for r in await cur.fetchall()]


class PgSubjectsQueries:
    """Adapter PostgreSQL implémentant `application.ports.subjects.SubjectsQueries`."""

    def upsert_subject(
        self,
        cur: Any,
        *,
        label: str,
        language: str | None = None,
        ontologies: dict[str, dict[str, Any]] | None = None,
    ) -> int:
        return upsert_subject(
            cur,
            label=label,
            language=language,
            ontologies=ontologies,
        )

    def link_publication_subjects_bulk(
        self,
        cur: Any,
        *,
        source: str,
        rows: list[tuple[int, int, float | None]],
    ) -> int:
        return link_publication_subjects_bulk(cur, source=source, rows=rows)

    def clear_links_for_source(self, cur: Any, *, source: str) -> int:
        return clear_links_for_source(cur, source=source)

    def select_source_publications_with_subjects(self, cur: Any, *, source: str) -> list[Any]:
        return select_source_publications_with_subjects(cur, source=source)

    def recompute_usage_counts(self, cur: Any) -> int:
        return recompute_usage_counts(cur)

    def recompute_cooccurrences(self, cur: Any, *, min_count: int = 2) -> int:
        return recompute_cooccurrences(cur, min_count=min_count)
