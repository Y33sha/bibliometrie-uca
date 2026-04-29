"""Query service : SQL pour la table `subjects` et la liaison
`publication_subjects`.

Consommé par la phase `application/pipeline/subjects/` (Phase 2 du chantier).
Voir docs/chantiers/sujets-mots-cles.md.

Toutes les fonctions sont synchrones (la phase pipeline tourne en sync, comme
les autres normalizers). Les services async qui auront besoin de lire les
sujets pour l'API (Phase 4+) auront leurs propres helpers.
"""

from typing import Any

from domain.subject import normalize_free_label


def upsert_free_subject(
    cur: Any,
    *,
    label: str,
    language: str | None = None,
) -> int:
    """UPSERT d'un mot-clé libre. Retourne l'id du subject.

    Déduplication sur `(lower(label), COALESCE(language, ''))` via l'index
    unique partiel `subjects_free_key`. La forme originale du premier insert
    est préservée dans `subjects.label`.

    `language` doit être un code ISO 639-1 ('fr', 'en', …) ou None.
    """
    normalized = normalize_free_label(label)
    cur.execute(
        """
        INSERT INTO subjects (kind, label, language)
        VALUES ('free', %s, %s)
        ON CONFLICT (lower(label), COALESCE(language, '')) WHERE kind = 'free'
        DO UPDATE SET label = subjects.label
        RETURNING id
        """,
        (normalized, language),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_concept_subject(
    cur: Any,
    *,
    ontology: str,
    ontology_id: str,
    label: str,
    language: str | None = None,
    parent_id: int | None = None,
    level: int | None = None,
) -> int:
    """UPSERT d'un concept ontologique. Retourne l'id du subject.

    Déduplication stricte sur `(ontology, ontology_id)`. Si le concept existe
    déjà, son `label`, `language`, `parent_id`, `level` sont rafraîchis
    (les ontologies peuvent évoluer entre deux extractions).
    """
    cur.execute(
        """
        INSERT INTO subjects (kind, label, language, ontology, ontology_id, parent_id, level)
        VALUES ('concept', %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ontology, ontology_id) WHERE kind = 'concept'
        DO UPDATE SET
            label = EXCLUDED.label,
            language = COALESCE(EXCLUDED.language, subjects.language),
            parent_id = COALESCE(EXCLUDED.parent_id, subjects.parent_id),
            level = COALESCE(EXCLUDED.level, subjects.level)
        RETURNING id
        """,
        (label, language, ontology, ontology_id, parent_id, level),
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
    """Bulk INSERT (avec ON CONFLICT) de liens publication↔subject pour une source.

    `rows` : liste de tuples `(publication_id, subject_id, score)`. Le
    `source` est constant pour le batch (l'orchestrateur traite une source
    à la fois). Idempotent grâce au `ON CONFLICT DO UPDATE SET score`.

    Retourne le nombre de lignes envoyées (pas insérées : `executemany`
    ne distingue pas inserts vs updates).
    """
    if not rows:
        return 0
    cur.executemany(
        """
        INSERT INTO publication_subjects (publication_id, subject_id, source, score)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (publication_id, subject_id, source)
        DO UPDATE SET score = EXCLUDED.score
        """,
        [(pub_id, sid, source, score) for pub_id, sid, score in rows],
    )
    return len(rows)


def clear_publication_subjects(
    cur: Any,
    *,
    publication_id: int,
    source: str,
) -> int:
    """Supprime tous les liens d'une publication pour une source.

    Appelé en début de réingestion d'une publication par une source pour
    garantir l'idempotence (si on retire un mot-clé entre deux fetchs, il
    disparaît bien). Retourne le nombre de lignes supprimées.
    """
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
    """Lit les `source_publications` rattachées à une publication canonique
    pour la source donnée, avec `keywords` et `topics`. Utilisé par
    l'orchestrateur de la phase `subjects`."""
    cur.execute(
        """
        SELECT publication_id, keywords, topics
        FROM source_publications
        WHERE source = %s AND publication_id IS NOT NULL
        """,
        (source,),
    )
    return cur.fetchall()


class PgSubjectsQueries:
    """Adapter PostgreSQL implémentant `application.ports.subjects.SubjectsQueries`."""

    def upsert_free_subject(self, cur: Any, *, label: str, language: str | None = None) -> int:
        return upsert_free_subject(cur, label=label, language=language)

    def upsert_concept_subject(
        self,
        cur: Any,
        *,
        ontology: str,
        ontology_id: str,
        label: str,
        language: str | None = None,
        parent_id: int | None = None,
        level: int | None = None,
    ) -> int:
        return upsert_concept_subject(
            cur,
            ontology=ontology,
            ontology_id=ontology_id,
            label=label,
            language=language,
            parent_id=parent_id,
            level=level,
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
