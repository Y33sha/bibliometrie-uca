"""Query service : SQL de construction de la table `authorships`.

Appelé par `application/pipeline/build/build_authorships.py`. Regroupe les
étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les
`source_authorships` en `authorships` consolidées.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.authorships_build import AuthorshipsBuildQueries
from domain.sources.registry import SOURCE_PRIORITY, source_case_sql


def insert_missing_authorships(conn: Connection) -> int:
    """Étape 1 : crée les `authorships` manquantes à partir des sources.

    Insère les paires `(publication_id, person_id)` présentes dans
    `source_authorships` (avec `person_id`) et dont la publication est
    active, si elles n'existent pas déjà **et ne sont pas rejetées**
    (anti-join sur `rejected_authorships`). Retourne le rowcount.
    """
    return conn.execute(
        text("""
            WITH all_pairs AS (
                SELECT DISTINCT sd.publication_id, sa.person_id
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                JOIN publications pub ON pub.id = sd.publication_id
                WHERE sa.person_id IS NOT NULL
            )
            INSERT INTO authorships (publication_id, person_id)
            SELECT ap.publication_id, ap.person_id
            FROM all_pairs ap
            WHERE NOT EXISTS (
                SELECT 1 FROM authorships a
                WHERE a.publication_id = ap.publication_id
                  AND a.person_id = ap.person_id
            )
              AND NOT EXISTS (
                SELECT 1 FROM rejected_authorships rj
                WHERE rj.publication_id = ap.publication_id
                  AND rj.person_id = ap.person_id
            )
        """)
    ).rowcount


def prune_orphan_authorships(conn: Connection) -> int:
    """Étape 1bis : supprime les `authorships` que plus aucune source n'atteste.

    Inverse exact d'`insert_missing_authorships` : une authorship `(publication_id,
    person_id)` dont la paire n'existe plus dans `source_authorships` (auteur retiré
    de toutes les sources lors d'un réimport) est orpheline et doit disparaître. Le
    build incrémental (modes daily/weekly) étant add-only, sans ce prune une telle
    orpheline survivrait jusqu'au prochain rebuild `full`. Tourne donc à chaque build.

    Version globale de `delete_orphan_authorships_for_person` (chemin admin detach),
    sans le filtre personne. Le DELETE délie `source_authorships.authorship_id` (FK
    ON DELETE SET NULL) — inerte ici, une orpheline n'ayant par définition aucun
    `source_authorship` lié. Retourne le nombre d'authorships purgées.
    """
    return conn.execute(
        text("""
            DELETE FROM authorships a
            WHERE NOT EXISTS (
                SELECT 1
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                WHERE sa.person_id = a.person_id
                  AND sd.publication_id = a.publication_id
            )
        """)
    ).rowcount


def link_source_authorships_to_authorships(conn: Connection) -> int:
    """Étape 2 : peuple `source_authorships.authorship_id` pour toutes les sources.

    Source-agnostique : un seul UPDATE sur l'ensemble des `source_authorships`
    encore non liées (l'ancien code bouclait par source). Retourne le nombre de
    lignes reliées.
    """
    return conn.execute(
        text("""
            UPDATE source_authorships sa
            SET authorship_id = a.id
            FROM source_publications sd
            JOIN authorships a ON a.publication_id = sd.publication_id
            WHERE sd.id = sa.source_publication_id
              AND sa.person_id IS NOT NULL
              AND a.person_id = sa.person_id
              AND sa.authorship_id IS NULL
        """)
    ).rowcount


def propagate_authorship_attributes(conn: Connection) -> int:
    """Étape 3 : recompose en une passe convergente les attributs dérivés de
    chaque authorship depuis ses `source_authorships` liées.

    - `author_position` : valeur de la source la plus prioritaire (`SOURCE_PRIORITY`)
      qui la renseigne — seul attribut qui exige de départager les sources.
    - `is_corresponding` : `bool_or` (vrai si au moins une source l'atteste). Pas de
      priorité : le FALSE des sources est une absence de signal, pas une
      non-correspondance — aucune source n'émet de FALSE explicite à écraser.
    - `in_perimeter` : `bool_or` de `source_authorships.in_perimeter`.
    - `roles` : union triée des rôles (au moins `{author}`, défaut côté SA).

    Convergente (`IS DISTINCT FROM`, sans garde `IS NULL`) : une valeur révisée en
    source se met à jour, une valeur que plus aucune source n'atteste retombe
    (TRUE périmé → FALSE, rôle disparu → retiré, périmètre perdu → FALSE). Source-
    agnostique : remplace les passes séquentielles per-attribut et la propagation
    de périmètre per-source. Retourne le nombre d'authorships modifiées.
    """
    return conn.execute(
        text(f"""
            WITH scal AS (
                SELECT sa.authorship_id AS aid,
                       (array_agg(sa.author_position ORDER BY
                           {source_case_sql(SOURCE_PRIORITY)})
                           FILTER (WHERE sa.author_position IS NOT NULL))[1] AS pos,
                       bool_or(sa.is_corresponding)              AS is_corr,
                       COALESCE(bool_or(sa.in_perimeter), FALSE) AS in_perim
                FROM source_authorships sa
                WHERE sa.authorship_id IS NOT NULL
                GROUP BY sa.authorship_id
            ),
            rol AS (
                SELECT sa.authorship_id AS aid,
                       array_agg(DISTINCT r ORDER BY r) AS roles
                FROM source_authorships sa, LATERAL unnest(sa.roles) AS r
                WHERE sa.authorship_id IS NOT NULL
                GROUP BY sa.authorship_id
            )
            UPDATE authorships a
            SET author_position = scal.pos,
                is_corresponding = scal.is_corr,
                in_perimeter     = scal.in_perim,
                roles            = rol.roles
            FROM scal LEFT JOIN rol ON rol.aid = scal.aid
            WHERE a.id = scal.aid
              AND (a.author_position, a.is_corresponding, a.in_perimeter, a.roles)
                  IS DISTINCT FROM (scal.pos, scal.is_corr, scal.in_perim, rol.roles)
        """)
    ).rowcount


def purge_authorships(conn: Connection) -> int:
    """Vide la table `authorships` et délie les `source_authorships` qui y pointaient.

    Utilisé en mode pipeline `full` pour garantir la convergence absolue : on repart de zéro et `build_authorships` reconstruit tout depuis les `source_authorships`. Le build incrémental (modes daily/weekly) ne déclenche pas ce purge, sa logique étant idempotente.

    Délie d'abord les `source_authorships.authorship_id` (FK ON DELETE SET NULL), puis DELETE de toutes les lignes. TRUNCATE refusé par Postgres dès lors qu'une FK existe (même `SET NULL` et même si aucune ligne ne référence) — DELETE contourne. Reset de la séquence d'identité ensuite pour cohérence avec l'ancien comportement. Retourne le nombre d'authorships purgées.
    """
    n = conn.execute(text("SELECT COUNT(*) FROM authorships")).scalar_one()
    conn.execute(
        text("UPDATE source_authorships SET authorship_id = NULL WHERE authorship_id IS NOT NULL")
    )
    conn.execute(text("DELETE FROM authorships"))
    conn.execute(text("ALTER SEQUENCE authorships_id_seq RESTART WITH 1"))
    return n


def refresh_authorship_structures(conn: Connection) -> None:
    """Rafraîchit la matview `authorship_structures` (`CONCURRENTLY` pour ne pas
    bloquer les lectures labo ; requiert l'index unique `(authorship_id, structure_id)`).

    À appeler après que `source_authorships.authorship_id` (étape 2 du build) et
    `source_authorship_structures` (phase `affiliations`) sont posés.
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY authorship_structures"))


def refresh_publication_structures(conn: Connection) -> None:
    """Rafraîchit la matview `publication_structures` (publi↔structure dédoublonnée,
    `CONCURRENTLY` ; requiert l'index unique `(publication_id, structure_id)`).

    Dérive d'`authorships` × `authorship_structures` : à appeler **après**
    `refresh_authorship_structures`. Sert la facette labos (COUNT par structure
    sans jointure authorships ni DISTINCT).
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_structures"))


def count_authorships_in_perimeter(conn: Connection) -> int:
    """Compte les `authorships` avec `in_perimeter = TRUE`."""
    return conn.execute(
        text("SELECT COUNT(*) AS n FROM authorships WHERE in_perimeter = TRUE")
    ).scalar_one()


def refresh_publications_in_perimeter(conn: Connection) -> int:
    """Matérialise `publications.in_perimeter` (rollup de `authorships.in_perimeter`).

    Une publication est in-perimeter si elle a au moins un authorship in-perimeter
    d'une personne non rejetée — exactement le prédicat du filtre SQL
    `publication_in_perimeter`. À appeler après l'étape 3 (qui pose
    `authorships.in_perimeter`). Idempotent : n'écrit que les lignes dont le flag
    change (`IS DISTINCT FROM`). Retourne le nombre de publications modifiées.
    """
    return conn.execute(
        text("""
            WITH perim AS (
                SELECT DISTINCT a.publication_id AS id
                FROM authorships a
                JOIN persons pe ON pe.id = a.person_id AND pe.rejected = FALSE
                WHERE a.in_perimeter = TRUE
            )
            UPDATE publications p
            SET in_perimeter = (p.id IN (SELECT id FROM perim))
            WHERE p.in_perimeter IS DISTINCT FROM (p.id IN (SELECT id FROM perim))
        """)
    ).rowcount


class PgAuthorshipsBuildQueries(AuthorshipsBuildQueries):
    """Adapter PostgreSQL pour `application.ports.authorships_build.AuthorshipsBuildQueries`."""

    def purge_authorships(self, conn: Connection) -> int:
        return purge_authorships(conn)

    def insert_missing_authorships(self, conn: Connection) -> int:
        return insert_missing_authorships(conn)

    def prune_orphan_authorships(self, conn: Connection) -> int:
        return prune_orphan_authorships(conn)

    def analyze_authorships(self, conn: Connection) -> None:
        # ANALYZE intra-transaction est valide : Postgres met à jour pg_statistic immédiatement, et le planner relit ces stats au moment où il prépare chaque requête suivante de la même session. Sans ça, l'UPDATE de l'étape 3 (`propagate_authorship_attributes`) part en Nested Loop sur estimate `rows=1` au lieu de Hash Join, bloquant le pipeline pendant des heures sur ~100 k authorships fraîchement insérées (null_frac obsolète à 0).
        conn.execute(text("ANALYZE authorships"))

    def link_source_authorships_to_authorships(self, conn: Connection) -> int:
        return link_source_authorships_to_authorships(conn)

    def analyze_source_authorships(self, conn: Connection) -> None:
        # Après l'étape 2, `source_authorships.authorship_id` vient d'être posé sur des centaines de milliers de lignes (non committé). Sans ce ANALYZE, le planner garde le null_frac committé (≈ 1, colonne quasi 100% NULL) et estime que le filtre `authorship_id IS NOT NULL` de l'étape 3 ne ramène rien → Nested Loop au lieu de Hash Aggregate. L'ANALYZE intra-transaction voit les mises à jour non committées de la transaction courante ; coût sub-seconde (échantillon fixe, indépendant des 9 M lignes).
        conn.execute(text("ANALYZE source_authorships"))

    def propagate_authorship_attributes(self, conn: Connection) -> int:
        return propagate_authorship_attributes(conn)

    def refresh_authorship_structures(self, conn: Connection) -> None:
        refresh_authorship_structures(conn)

    def refresh_publication_structures(self, conn: Connection) -> None:
        refresh_publication_structures(conn)

    def count_authorships_in_perimeter(self, conn: Connection) -> int:
        return count_authorships_in_perimeter(conn)

    def refresh_publications_in_perimeter(self, conn: Connection) -> int:
        return refresh_publications_in_perimeter(conn)
