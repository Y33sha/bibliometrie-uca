"""Query service : SQL de la phase `match_or_create_publications`.

Appelé par `application/pipeline/publications/match_or_create_publications.py`. Trois SELECT / UPDATE :

1. **Phase A — SELECT in_perimeter orphans** (`fetch_orphan_in_perimeter_source_publications`) : seuls les orphelins avec ≥1 source_authorship in_perimeter, traités via la cascade Python `decide_publication_match` qui peut créer ou rattacher.
2. **Phase B — UPDATEs bulk hors-périmètre** (`bulk_link_remaining_orphans`) : 3 UPDATEs SQL set-based qui rattachent les orphelins restants par DOI, NNT, hal_id. Pas de création. Bénéficie naturellement des publications créées en Phase A.
3. **SELECT publications stale** (`fetch_stale_publication_ids`) pour ré-agrégation des méta canoniques.

L'attachement d'un `source_publications` à un `publications` est mutualisé avec le script de fusion (voir `queries.merge.link_source_publication_to_publication`).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.publications_match_or_create import (
    BulkLinkCounts,
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
                   sd.language, sd.container_title, sd.external_ids,
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


def bulk_link_remaining_orphans(conn: Connection) -> BulkLinkCounts:
    """Rattache en bulk les orphelins restants (post-Phase A) par DOI, NNT, hal_id.

    3 UPDATEs SQL set-based, équivalent fonctionnel de la cascade Python sur les voies « match seul » (sans création, ni dédup métadonnées thèse). Bénéficie des publications créées en Phase A puisqu'elle tourne après. Pas de `resolve_doi_conflict` : les cas chapter/book limites sont rares en pratique, traitables en aval via admin/duplicates ; le gain de simplicité et de vitesse compense.

    Pas de `refresh_from_sources` ici non plus — pas pertinent puisqu'on n'a fait que du rattachement (les métadonnées des publis canoniques sont déjà figées pour ce run, la phase 2 du `run()` les recomposera via `fetch_stale_publication_ids`).
    """
    n_doi = conn.execute(
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

    n_nnt = conn.execute(
        text("""
            UPDATE source_publications sp
            SET publication_id = p.id
            FROM publications p
            WHERE sp.publication_id IS NULL
              AND p.nnt IS NOT NULL
              AND (sp.external_ids ->> 'nnt') = p.nnt
        """)
    ).rowcount

    n_hal_id = conn.execute(
        text("""
            UPDATE source_publications sp
            SET publication_id = sphal.publication_id
            FROM source_publications sphal
            WHERE sp.publication_id IS NULL
              AND sphal.source = 'hal'
              AND sphal.publication_id IS NOT NULL
              AND (sp.external_ids ->> 'hal_id') = sphal.source_id
        """)
    ).rowcount

    return BulkLinkCounts(by_doi=n_doi, by_nnt=n_nnt, by_hal_id=n_hal_id)


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


class PgPublicationsMatchOrCreateQueries(PublicationsMatchOrCreateQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.publications_match_or_create.PublicationsMatchOrCreateQueries`.

    Délègue `link_source_publication_to_publication` à
    `infrastructure.queries.merge` (même SQL).
    """

    def fetch_orphan_in_perimeter_source_publications(
        self, conn: Connection
    ) -> list[SourcePublicationRow]:
        return fetch_orphan_in_perimeter_source_publications(conn)

    def bulk_link_remaining_orphans(self, conn: Connection) -> BulkLinkCounts:
        return bulk_link_remaining_orphans(conn)

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

    def fetch_stale_publication_ids(self, conn: Connection) -> list[int]:
        return fetch_stale_publication_ids(conn)
