"""Query service : SQL de la phase `create_publications`.

Appelé par `application/pipeline/publications/match_or_create_publications.py` (modèle création⇒fusion) :

1. **Création** (`fetch_orphan_source_publications`) : tous les orphelins (`publication_id IS NULL`), chacun donnant une publication canonique. Le dédoublonnage est délégué aux passes de fusion (identifiants puis métadonnées).
2. **SELECT publications stale** (`fetch_stale_publication_ids`) pour ré-agrégation des métadonnées canoniques.

Les lectures de critères (auteur primary thèse, nombre d'auteurs) servent aux passes de fusion par métadonnées.

L'attachement d'un `source_publications` à un `publications` est mutualisé avec le script de fusion (voir `queries.pipeline.merge.link_source_publication_to_publication`).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.publications_match_or_create import (
    PublicationsMatchOrCreateQueries,
    SourcePublicationRow,
)
from domain.persons.name_matching import parse_raw_author_name


def fetch_orphan_source_publications(
    conn: Connection,
) -> list[SourcePublicationRow]:
    """Tous les orphelins (`publication_id IS NULL`).

    Modèle création⇒fusion : chaque orphelin donne une publication canonique
    (sans gate périmètre ni matching). Le dédoublonnage est assuré en aval par
    les passes de fusion (identifiants puis métadonnées).
    """
    rows = conn.execute(
        text("""
            SELECT sd.id, sd.source::text AS source, sd.source_id, sd.doi, sd.title, sd.pub_year,
                   sd.doc_type::text AS doc_type, sd.journal_id, sd.oa_status::text AS oa_status,
                   sd.language, sd.container_title, sd.external_ids, sd.urls
            FROM source_publications sd
            WHERE sd.publication_id IS NULL
            ORDER BY sd.id
        """)
    ).all()
    return [SourcePublicationRow(**r._mapping) for r in rows]


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
    """Compte les `source_authorships` d'un `source_publication`."""
    row = conn.execute(
        text("""
            SELECT COUNT(*) AS n
            FROM source_authorships
            WHERE source_publication_id = :spid
        """),
        {"spid": source_publication_id},
    ).one()
    return row.n


def fetch_max_source_authorship_count_per_publication(conn: Connection, publication_id: int) -> int:
    """Pour une publication canonique, retourne le `MAX` du nombre de
    `source_authorships` par source. Chaque source rapporte
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
                WHERE sp.publication_id = :pid
                GROUP BY sp.source
            ) per_source
        """),
        {"pid": publication_id},
    ).one()
    return row.max_n


class PgPublicationsMatchOrCreateQueries(PublicationsMatchOrCreateQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.publications_match_or_create.PublicationsMatchOrCreateQueries`.

    Délègue `link_source_publication_to_publication` à
    `infrastructure.queries.pipeline.merge` (même SQL).
    """

    def fetch_orphan_source_publications(self, conn: Connection) -> list[SourcePublicationRow]:
        return fetch_orphan_source_publications(conn)

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None:
        from infrastructure.queries.pipeline.merge import link_source_publication_to_publication

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
