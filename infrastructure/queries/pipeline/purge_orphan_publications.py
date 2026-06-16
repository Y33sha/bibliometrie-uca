"""Purge des publications orphelines (zéro authorship), en fin de phase authorships.

Une publication sans aucun authorship n'a pas d'auteur rattaché à la base UCA :
elle est hors-périmètre (`in_perimeter` toujours false) et inatteignable dans
l'UI (les listes sont scopées périmètre, les fiches personne passent par les
authorships). Le modèle création⇒fusion promeut une publication par
`source_publication` orphelin sans gate ; les sources qui partagent un
identifiant avec une publication gardée ont fusionné *avant* cette phase (et lui
ont apporté leurs métadonnées). Une publication restée à zéro authorship après
toutes les passes de fusion ne contribue donc plus à rien.

Effet de bord voulu : `publication_subjects` (FK `ON DELETE CASCADE`) reste
naturellement scopé périmètre sans filtre propre — `subjects.usage_count` et la
matview `subject_cooccurrences` en héritent. Et les phases countries/subjects qui
suivent traitent ~58 % de publications en moins.

Tapis roulant assumé : `create_publications` re-promeut ces orphelins au run
suivant (`source_publications.publication_id` repasse à NULL via `ON DELETE SET
NULL`), ils re-fusionnent — ce qui rattrape les sources sœurs arrivées entre les
runs — puis sont re-purgés. Le `VACUUM ANALYZE` qui suit rend l'espace des tuples
morts réutilisable par les INSERT du run suivant : pas de bloat cumulatif et pas
de lock exclusif, contrairement à un `VACUUM FULL` qui réécrirait la table à
chaque run pour rien.
"""

from sqlalchemy import Connection, text

# Tables churnées par la purge et la re-création du run suivant, d'après les
# `ON DELETE` des FK vers `publications` : la table elle-même, son détail
# (CASCADE) et les `source_publications` dont le `publication_id` repasse à NULL
# (SET NULL). Liste constante — interpolée en SQL VACUUM (pas de bind possible
# sur un nom de table, aucune valeur utilisateur).
CHURNED_TABLES: tuple[str, ...] = ("publications", "publications_detail", "source_publications")


def purge_orphan_publications(conn: Connection, *, limit: int | None = None) -> int:
    """Supprime les publications sans aucun authorship. Retourne le nombre supprimé.

    Prédicat : zéro authorship actif. Sans perte de curation ni de donnée métier
    (mesuré : 0 `rejected_authorships`, 0 `apc_payments` sur ces publications) ;
    les éventuels marqueurs `distinct_publications` partent en CASCADE (paires
    marquées par l'admin sur une publication purgée — cas marginal).

    `limit` borne le nombre de publications supprimées par appel (un chunk) ;
    `None` = tout en une fois. Le batching — boucler sur des chunks avec un commit
    entre chaque — est orchestré par le caller (cf. `run_pipeline`) : il étale le
    WAL (le premier run cascade ~1,4M `publication_subjects` legacy) et rend la
    progression durable face à une interruption, sans bloquer les lectures (un
    DELETE prend `ROW EXCLUSIVE`, pas de conflit avec les SELECT).
    """
    limit_clause = "LIMIT :lim" if limit is not None else ""
    return conn.execute(
        text(
            f"""
            DELETE FROM publications
            WHERE id IN (
                SELECT p.id FROM publications p
                WHERE NOT EXISTS (
                    SELECT 1 FROM authorships a WHERE a.publication_id = p.id
                )
                {limit_clause}
            )
            """
        ),
        {"lim": limit} if limit is not None else {},
    ).rowcount


def vacuum_analyze_churned(conn: Connection) -> None:
    """`VACUUM ANALYZE` des tables churnées par la purge.

    `conn` doit être en autocommit (`isolation_level="AUTOCOMMIT"`) : `VACUUM` ne
    peut pas s'exécuter dans une transaction.
    """
    for table in CHURNED_TABLES:
        conn.execute(text(f"VACUUM ANALYZE {table}"))
