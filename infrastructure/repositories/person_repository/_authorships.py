"""SQL pour les liens personne ↔ `source_authorships` et les authorships."""

from sqlalchemy import Connection, text

from domain.sources import AUTHOR_SOURCES_SQL, source_case_sql


def link_authorship(
    conn: Connection,
    person_id: int,
    source: str,
    authorship_id: int,
) -> None:
    """Rattache une authorship source à une personne.

    Le matching par idhal/hal_person_id agrégé sera réintroduit dans
    le chantier `METIER_decide-person-match`.
    """
    conn.execute(
        text("UPDATE source_authorships SET person_id = :pid WHERE id = :aid AND source = :src"),
        {"pid": person_id, "aid": authorship_id, "src": source},
    )


def unlink_authorship(conn: Connection, person_id: int, source: str, authorship_id: int) -> None:
    conn.execute(
        text("""
            UPDATE source_authorships SET person_id = NULL
            WHERE id = :aid AND person_id = :pid AND source = :src
        """),
        {"aid": authorship_id, "pid": person_id, "src": source},
    )


def assign_orphan_sa(
    conn: Connection, person_id: int, source: str, authorship_id: int
) -> dict | None:
    """Tente de poser person_id sur une source_authorship orpheline.

    Retourne un dict {author_name_normalized} si l'UPDATE a touché une
    ligne, None si déjà attribuée à une autre personne.
    """
    row = conn.execute(
        text("""
            UPDATE source_authorships SET person_id = :pid
            WHERE id = :aid AND source = :src AND person_id IS NULL
            RETURNING author_name_normalized
        """),
        {"pid": person_id, "aid": authorship_id, "src": source},
    ).first()
    return dict(row._mapping) if row else None


# ── Opérations atomiques pour le use case `assign_orphans` ──────────
# Ces fonctions sont orchestrées par `application/authorships/assign_orphans.py`.
# Chaque fonction = une requête SQL ; aucune décision métier (les
# priorités de sources sont passées en paramètre par le use case).


def assign_orphan_source_authorships_to_person(
    conn: Connection, person_id: int, sa_ids: list[int]
) -> int:
    """Pose `person_id` sur les source_authorships du lot qui sont orphelines.

    Retourne le nombre de lignes effectivement modifiées (celles qui
    étaient `person_id IS NULL`). Les autres sont laissées intactes.
    """
    if not sa_ids:
        return 0
    return conn.execute(
        text("""
            UPDATE source_authorships SET person_id = :pid
            WHERE id = ANY(:ids) AND person_id IS NULL
            RETURNING id
        """),
        {"pid": person_id, "ids": sa_ids},
    ).rowcount


def create_authorships_from_sources(
    conn: Connection,
    person_id: int,
    sa_ids: list[int],
    source_priority: tuple[str, ...],
) -> None:
    """Crée les authorships manquantes pour la personne, depuis les sources.

    Pour chaque `publication_id` distinct du lot, insère une row dans
    `authorships` en prenant les colonnes (author_position, in_perimeter,
    is_corresponding) et les structures depuis la source de plus haute
    priorité (paramétrée par le use case). Les structures sont insérées
    dans la table de jointure `authorship_structures`.
    """
    if not sa_ids:
        return
    conn.execute(
        text(f"""
            CREATE TEMP TABLE _chosen_sa AS
            SELECT DISTINCT ON (sd.publication_id)
                sd.publication_id, sa.id AS sa_id,
                sa.author_position, sa.in_perimeter, sa.is_corresponding
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.id = ANY(:ids) AND sd.publication_id IS NOT NULL
            ORDER BY sd.publication_id, {source_case_sql(source_priority)}
        """),
        {"ids": sa_ids},
    )
    conn.execute(
        text("""
            INSERT INTO authorships (publication_id, person_id,
                author_position, in_perimeter, is_corresponding)
            SELECT publication_id, :pid, author_position, in_perimeter, is_corresponding
            FROM _chosen_sa
            ON CONFLICT (publication_id, person_id) DO NOTHING
        """),
        {"pid": person_id},
    )
    conn.execute(
        text("""
            INSERT INTO authorship_structures (authorship_id, structure_id)
            SELECT DISTINCT a.id, sas.structure_id
            FROM _chosen_sa cs
            JOIN authorships a ON a.publication_id = cs.publication_id
                              AND a.person_id = :pid
            JOIN source_authorship_structures sas ON sas.source_authorship_id = cs.sa_id
            ON CONFLICT DO NOTHING
        """),
        {"pid": person_id},
    )
    conn.execute(text("DROP TABLE _chosen_sa"))


def link_source_authorships_to_authorships(
    conn: Connection, person_id: int, sa_ids: list[int]
) -> None:
    """Pose `source_authorships.authorship_id` vers l'authorship canonique
    de la même paire (publication, person), pour les lignes du lot.

    N'écrase que les FK encore NULL (idempotent).
    """
    if not sa_ids:
        return
    conn.execute(
        text("""
            UPDATE source_authorships sa SET authorship_id = a.id
            FROM source_publications sd, authorships a
            WHERE sa.id = ANY(:ids)
              AND sd.id = sa.source_publication_id
              AND a.publication_id = sd.publication_id
              AND a.person_id = :pid
              AND sa.authorship_id IS NULL
        """),
        {"ids": sa_ids, "pid": person_id},
    )


def get_distinct_name_forms_from_source_authorships(
    conn: Connection, sa_ids: list[int]
) -> list[str]:
    """Retourne les `author_name_normalized` distincts observés dans le lot."""
    if not sa_ids:
        return []
    rows = conn.execute(
        text("""
            SELECT DISTINCT author_name_normalized
            FROM source_authorships
            WHERE id = ANY(:ids)
              AND author_name_normalized IS NOT NULL
        """),
        {"ids": sa_ids},
    ).all()
    return [row.author_name_normalized for row in rows]


def find_publication_id_for_source_authorship(
    conn: Connection, source: str, authorship_id: int
) -> int | None:
    """Résout la `publication_id` côté `source_publications` pour une
    source_authorship donnée. None si la sa n'existe pas ou n'est pas
    rattachée à une publication."""
    return conn.execute(
        text("""
            SELECT d.publication_id FROM source_authorships sa
            JOIN source_publications d ON d.id = sa.source_publication_id
            WHERE sa.id = :aid AND sa.source = :src
        """),
        {"aid": authorship_id, "src": source},
    ).scalar_one_or_none()


def insert_authorship_if_missing(conn: Connection, publication_id: int, person_id: int) -> None:
    """INSERT ... ON CONFLICT DO NOTHING dans `authorships` pour la paire."""
    conn.execute(
        text("""
            INSERT INTO authorships (publication_id, person_id)
            VALUES (:pub, :pid)
            ON CONFLICT (publication_id, person_id) DO NOTHING
        """),
        {"pub": publication_id, "pid": person_id},
    )


def link_source_authorships_to_authorship_for_pair(
    conn: Connection, publication_id: int, person_id: int
) -> None:
    """Pose `source_authorships.authorship_id` pour la paire (publication,
    person), sur toutes les sa encore non liées."""
    conn.execute(
        text("""
            UPDATE source_authorships sa
            SET authorship_id = a.id
            FROM source_publications sd, authorships a
            WHERE sd.id = sa.source_publication_id
              AND a.publication_id = sd.publication_id
              AND a.person_id = sa.person_id
              AND sd.publication_id = :pub
              AND sa.person_id = :pid
              AND sa.authorship_id IS NULL
        """),
        {"pub": publication_id, "pid": person_id},
    )


def recompute_authorship_author_position_and_corresponding(
    conn: Connection,
    publication_id: int,
    person_id: int,
    source_priority: tuple[str, ...],
    is_corresponding_priority: tuple[str, ...],
) -> None:
    """Réagrège `authorships.author_position` et `is_corresponding` pour la
    paire, depuis les sources actives, selon les priorités fournies."""
    conn.execute(
        text(f"""
            UPDATE authorships a
            SET author_position = sub.pos,
                is_corresponding = COALESCE(a.is_corresponding, sub.corr)
            FROM (
                SELECT sa.authorship_id,
                       (array_agg(sa.author_position ORDER BY
                           {source_case_sql(source_priority)}
                       ))[1] AS pos,
                       (array_agg(sa.is_corresponding ORDER BY
                           {source_case_sql(is_corresponding_priority)}
                       ))[1] AS corr
                FROM source_authorships sa
                WHERE sa.authorship_id IS NOT NULL
                GROUP BY sa.authorship_id
            ) sub
            WHERE a.id = sub.authorship_id
              AND a.publication_id = :pub AND a.person_id = :pid
        """),
        {"pub": publication_id, "pid": person_id},
    )


def recompute_authorship_in_perimeter_and_structures(
    conn: Connection,
    publication_id: int,
    person_id: int,
    sources: tuple[str, ...],
) -> None:
    """Réagrège `authorships.in_perimeter` (OR-bool des sources) et resync
    `authorship_structures` (union des structures cross-source) pour la paire."""
    sources_sql = "(" + ", ".join(f"'{s}'" for s in sources) + ")"
    conn.execute(
        text(f"""
            UPDATE authorships a
            SET in_perimeter = COALESCE((
                    SELECT bool_or(sa.in_perimeter)
                    FROM source_authorships sa
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE sa.source IN {sources_sql}
                      AND sd.publication_id = :pub
                      AND sa.person_id = :pid
                ), FALSE),
                updated_at = now()
            WHERE a.publication_id = :pub AND a.person_id = :pid
        """),
        {"pub": publication_id, "pid": person_id},
    )
    conn.execute(
        text("""
            DELETE FROM authorship_structures aus
            USING authorships a
            WHERE aus.authorship_id = a.id
              AND a.publication_id = :pub AND a.person_id = :pid
        """),
        {"pub": publication_id, "pid": person_id},
    )
    conn.execute(
        text(f"""
            INSERT INTO authorship_structures (authorship_id, structure_id)
            SELECT DISTINCT a.id, sas.structure_id
            FROM authorships a
            JOIN source_publications sd ON sd.publication_id = a.publication_id
            JOIN source_authorships sa ON sa.source_publication_id = sd.id
                                       AND sa.person_id = a.person_id
                                       AND sa.source IN {sources_sql}
            JOIN source_authorship_structures sas ON sas.source_authorship_id = sa.id
            WHERE a.publication_id = :pub AND a.person_id = :pid
        """),
        {"pub": publication_id, "pid": person_id},
    )


def count_authorships_with_name_form(conn: Connection, person_id: int, name_form: str) -> int:
    """Compte les source_authorships actives d'une personne portant une
    forme de nom donnée. Utilisé par detach_authorships pour décider
    de nettoyer la name_form ou pas."""
    return conn.execute(
        text(f"""
            SELECT COUNT(*) AS n FROM source_authorships sa
            WHERE sa.person_id = :pid AND sa.author_name_normalized = :nf
              AND sa.source IN {AUTHOR_SOURCES_SQL}
        """),
        {"pid": person_id, "nf": name_form},
    ).scalar_one()
