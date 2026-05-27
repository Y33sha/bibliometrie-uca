"""Query service : SQL de la phase `match_or_create_publications`.

Appelé par `application/pipeline/publications/match_or_create_publications.py`. Trois SELECT / UPDATE :

1. **Phase A — SELECT in_perimeter orphans** (`fetch_orphan_in_perimeter_source_publications`) : seuls les orphelins avec ≥1 source_authorship in_perimeter, traités via la cascade Python `decide_publication_match` qui peut créer ou rattacher.
2. **Phase B — UPDATEs bulk hors-périmètre** (`bulk_link_remaining_orphans`) : 3 UPDATEs SQL set-based qui rattachent les orphelins restants par DOI, NNT, hal_id. Pas de création. Bénéficie naturellement des publications créées en Phase A.
3. **SELECT publications stale** (`fetch_stale_publication_ids`) pour ré-agrégation des méta canoniques.

L'attachement d'un `source_publications` à un `publications` est mutualisé avec le script de fusion (voir `queries.merge.link_source_publication_to_publication`).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.publications_match_or_create import (
    PublicationsMatchOrCreateQueries,
    SourcePublicationRow,
)
from domain.persons.name_matching import parse_raw_author_name


def fetch_orphan_in_perimeter_source_publications(
    conn: Connection,
) -> list[SourcePublicationRow]:
    """Orphelins (`publication_id IS NULL`) avec ≥1 source_authorship in_perimeter.

    Périmètre de la Phase A : seuls candidats à la création d'une publication canonique. Les orphelins hors-périmètre (≈ 98 % du pool typiquement) ne sont pas remontés ici — ils seront traités en Phase B par `bulk_link_remaining_orphans`, qui ne fait que du rattachement set-based, beaucoup moins coûteux qu'une itération Python.
    """
    rows = conn.execute(
        text("""
            SELECT sd.id, sd.source::text AS source, sd.source_id, sd.doi, sd.title, sd.pub_year,
                   sd.doc_type::text AS doc_type, sd.journal_id, sd.oa_status::text AS oa_status,
                   sd.language, sd.container_title, sd.external_ids, sd.urls,
                   TRUE AS in_perimeter
            FROM source_publications sd
            WHERE sd.publication_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM source_authorships sa
                  WHERE sa.source_publication_id = sd.id AND sa.in_perimeter = TRUE
              )
            ORDER BY sd.id
        """)
    ).all()
    return [SourcePublicationRow(**r._mapping) for r in rows]


def bulk_link_orphans_by_doi(conn: Connection) -> int:
    """Rattache les orphelins par DOI (exact match contre `publications.doi`).

    Rapide grâce à `idx_source_pubs_doi` + index sur `publications.doi`.
    """
    return conn.execute(
        text("""
            UPDATE source_publications sp
            SET publication_id = p.id
            FROM publications p
            WHERE sp.publication_id IS NULL
              AND sp.doi IS NOT NULL
              AND p.doi IS NOT NULL
              AND sp.doi = p.doi
        """)
    ).rowcount


def bulk_link_orphans_by_nnt(conn: Connection) -> int:
    """Rattache les orphelins par NNT (stocké sur `source_publications.external_ids`).

    CTE de lookup `(nnt, publication_id)` matérialisée d'abord, puis JOIN avec les orphans — évite un self-join 11M × 11M en JSONB extraction qui mettait >10 min.
    """
    return conn.execute(
        text("""
            WITH nnt_lookup AS (
                SELECT (external_ids->>'nnt') AS nnt,
                       MIN(publication_id) AS publication_id
                FROM source_publications
                WHERE publication_id IS NOT NULL
                  AND external_ids ? 'nnt'
                GROUP BY (external_ids->>'nnt')
            )
            UPDATE source_publications sp
            SET publication_id = nl.publication_id
            FROM nnt_lookup nl
            WHERE sp.publication_id IS NULL
              AND sp.external_ids ? 'nnt'
              AND (sp.external_ids ->> 'nnt') = nl.nnt
        """)
    ).rowcount


def bulk_link_orphans_by_hal_id(conn: Connection) -> int:
    """Rattache les orphelins par hal_id.

    Deux paths de donor (cf. `PublicationRepository.find_by_hal_id`) :
    SP HAL native via `source_id`, OU SP cross-source via
    `external_ids->>'hal_id'`. Unifiés dans une CTE de lookup matérialisée.
    """
    return conn.execute(
        text("""
            WITH hal_id_lookup AS (
                SELECT key, MIN(publication_id) AS publication_id
                FROM (
                    SELECT source_id AS key, publication_id
                    FROM source_publications
                    WHERE source = 'hal' AND publication_id IS NOT NULL
                    UNION ALL
                    SELECT external_ids->>'hal_id' AS key, publication_id
                    FROM source_publications
                    WHERE publication_id IS NOT NULL
                      AND external_ids ? 'hal_id'
                ) u
                WHERE key IS NOT NULL
                GROUP BY key
            )
            UPDATE source_publications sp
            SET publication_id = hl.publication_id
            FROM hal_id_lookup hl
            WHERE sp.publication_id IS NULL
              AND sp.external_ids ? 'hal_id'
              AND (sp.external_ids ->> 'hal_id') = hl.key
        """)
    ).rowcount


def fetch_thesis_primary_author(conn: Connection, publication_id: int) -> tuple[str, str] | None:
    """Retourne `(last_name, first_name)` de l'auteur principal d'une publication thèse existante.

    Rôle `author`, tri par (source_publication_id, author_position), 1 ligne max. Parse via `domain.names.parse_raw_author_name`.
    """
    row = conn.execute(
        text("""
            SELECT sas.raw_author_name
            FROM source_authorships sas
            JOIN source_publications sd ON sd.id = sas.source_publication_id
            WHERE sd.publication_id = :pid
              AND 'author' = ANY(sas.roles)
            ORDER BY sd.id, sas.author_position
            LIMIT 1
        """),
        {"pid": publication_id},
    ).one_or_none()
    if row is None or not row.raw_author_name:
        return None
    last, first = parse_raw_author_name(row.raw_author_name)
    return (last, first) if last else None


def fetch_stale_publication_ids(conn: Connection) -> list[int]:
    """Publications dont au moins un `source_publication` a été modifié depuis le dernier refresh canonique.

    Comparaison `source_publications.updated_at > publications.updated_at` : indique qu'une normalisation récente a apporté des changements de méta (oa_status, abstract, biblio, …) que le canonique ne reflète pas encore. `refresh_from_sources` recalcule les méta agrégées et met `publications.updated_at = now()` au passage, ce qui ferme la fenêtre.
    """
    rows = conn.execute(
        text("""
            SELECT p.id
            FROM publications p
            WHERE EXISTS (
                SELECT 1 FROM source_publications sp
                WHERE sp.publication_id = p.id
                  AND sp.updated_at > p.updated_at
            )
            ORDER BY p.id
        """)
    ).all()
    return [row.id for row in rows]


def fetch_thesis_primary_author_from_source_publication(
    conn: Connection, source_publication_id: int
) -> tuple[str, str] | None:
    """Retourne `(last_name, first_name)` de l'auteur principal d'un `source_publication` courant (avant rattachement canonique).

    Rôle `author`, tri par `author_position`, 1 ligne max. Parse via `domain.names.parse_raw_author_name`.
    """
    row = conn.execute(
        text("""
            SELECT raw_author_name
            FROM source_authorships
            WHERE source_publication_id = :spid
              AND 'author' = ANY(roles)
            ORDER BY author_position
            LIMIT 1
        """),
        {"spid": source_publication_id},
    ).one_or_none()
    if row is None or not row.raw_author_name:
        return None
    last, first = parse_raw_author_name(row.raw_author_name)
    return (last, first) if last else None


def fetch_source_authorship_count(conn: Connection, source_publication_id: int) -> int:
    """Compte les `source_authorships` non-excluded d'un `source_publication`."""
    row = conn.execute(
        text("""
            SELECT COUNT(*) AS n
            FROM source_authorships
            WHERE source_publication_id = :spid AND NOT excluded
        """),
        {"spid": source_publication_id},
    ).one()
    return row.n


def fetch_max_source_authorship_count_per_publication(conn: Connection, publication_id: int) -> int:
    """Pour une publication canonique, retourne le `MAX` du nombre de
    `source_authorships` non-excluded par source. Chaque source rapporte
    sa propre liste d'auteurs ; on retient la plus complète comme
    représentative du « vrai » nombre d'auteurs de la publication.

    Retourne 0 si la publication n'a aucun `source_authorship`.
    """
    row = conn.execute(
        text("""
            SELECT COALESCE(MAX(n), 0) AS max_n
            FROM (
                SELECT COUNT(*) AS n
                FROM source_publications sp
                JOIN source_authorships sa ON sa.source_publication_id = sp.id
                WHERE sp.publication_id = :pid AND NOT sa.excluded
                GROUP BY sp.source
            ) per_source
        """),
        {"pid": publication_id},
    ).one()
    return row.max_n


class PgPublicationsMatchOrCreateQueries(PublicationsMatchOrCreateQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.publications_match_or_create.PublicationsMatchOrCreateQueries`.

    Délègue `link_source_publication_to_publication` à
    `infrastructure.queries.merge` (même SQL).
    """

    def fetch_orphan_in_perimeter_source_publications(
        self, conn: Connection
    ) -> list[SourcePublicationRow]:
        return fetch_orphan_in_perimeter_source_publications(conn)

    def bulk_link_orphans_by_doi(self, conn: Connection) -> int:
        return bulk_link_orphans_by_doi(conn)

    def bulk_link_orphans_by_nnt(self, conn: Connection) -> int:
        return bulk_link_orphans_by_nnt(conn)

    def bulk_link_orphans_by_hal_id(self, conn: Connection) -> int:
        return bulk_link_orphans_by_hal_id(conn)

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None:
        from infrastructure.queries.merge import link_source_publication_to_publication

        link_source_publication_to_publication(conn, source_publication_id, publication_id)

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None:
        return fetch_thesis_primary_author(conn, publication_id)

    def fetch_thesis_primary_author_from_source_publication(
        self, conn: Connection, source_publication_id: int
    ) -> tuple[str, str] | None:
        return fetch_thesis_primary_author_from_source_publication(conn, source_publication_id)

    def fetch_source_authorship_count(self, conn: Connection, source_publication_id: int) -> int:
        return fetch_source_authorship_count(conn, source_publication_id)

    def fetch_max_source_authorship_count_per_publication(
        self, conn: Connection, publication_id: int
    ) -> int:
        return fetch_max_source_authorship_count_per_publication(conn, publication_id)

    def fetch_stale_publication_ids(self, conn: Connection) -> list[int]:
        return fetch_stale_publication_ids(conn)
