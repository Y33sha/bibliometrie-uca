"""SQL de la passe de réconciliation des composantes (phase `publications`)."""

from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.merge import MergedEntity
from domain.source_publications.external_ids import ExternalIdType
from domain.source_publications.keys import (
    DISCRIMINANT_TITLE_MIN_LENGTH,
    SCALAR_CONFIRMATION_ID_TYPES,
)
from domain.types import JsonValue
from infrastructure.db.scalars import scalar_int
from infrastructure.repositories.merge_steps import record_redirect


class ReconcileRow(NamedTuple):
    """Projection d'une `source_publication` du voisinage : clés + publication courante.

    `doc_type`/`title_normalized`/`pub_year` alimentent le token métadonnée thèse de `project_confirmation_keys` (les identifiants viennent de `doi`/`external_ids`).
    `publication_id` = `None` si orpheline ; `publication_doi` = DOI canonique de la publication courante (`None` si orpheline), pour choisir l'ancre ; `in_perimeter` = la SP a ≥1 authorship in-périmètre (gate de création d'une pub neuve)."""

    id: int
    doi: str | None
    external_ids: dict[str, JsonValue] | None
    publication_id: int | None
    doc_type: str | None
    title_normalized: str | None
    pub_year: int | None
    publication_doi: str | None
    in_perimeter: bool


# Voisinage 1-hop : les `source_publications` dirty (orphelines comprises) et celles qui
# partagent une clé de confirmation avec elles. Une branche UNION par type de clé (chacune
# annotée en ligne). `publication_doi` (via LEFT JOIN) choisit l'ancre ; `in_perimeter`
# (EXISTS) gate la création d'une pub neuve pour une partition d'orphelins.
_COLS = (
    "{a}.id, {a}.doi, {a}.external_ids, {a}.publication_id, "
    "{a}.doc_type, {a}.title_normalized, {a}.pub_year, p.doi AS publication_doi, "
    "EXISTS (SELECT 1 FROM source_authorships sa "
    "WHERE sa.source_publication_id = {a}.id AND sa.in_perimeter) AS in_perimeter"
)

# Premier identifiant HAL que liste une `source_publication` : sa clé de fusion HAL.
_FIRST_HAL_ID = "(({a}.external_ids -> '" + ExternalIdType.HAL_ID + "') ->> 0)"

# Un bras UNION par clé de confirmation scalaire d'`external_ids` : égalité directe (index btree). `hal_id` (array) a son propre bras.
_SCALAR_KEY_ARMS = "".join(
    f"""
    UNION
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o ON o.external_ids ->> '{k}' = d.external_ids ->> '{k}'
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.external_ids ? '{k}'"""
    for k in SCALAR_CONFIRMATION_ID_TYPES
)

_UNIVERSE_SQL = text(f"""
    WITH dirty AS (
        SELECT {_COLS.format(a="sd")}
        FROM source_publications sd
        LEFT JOIN publications p ON p.id = sd.publication_id
        WHERE sd.keys_dirty
    )
    SELECT id, doi, external_ids, publication_id, doc_type, title_normalized, pub_year,
           publication_doi, in_perimeter
    FROM dirty
    UNION
    -- DOI : égalité directe (la colonne est toujours normalisée minuscule par `clean_doi` à
    -- l'écriture), pour utiliser l'index btree `idx_source_pubs_doi` plutôt qu'un scan via `lower()`.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o ON o.doi IS NOT NULL AND o.doi = d.doi
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.doi IS NOT NULL
    {_SCALAR_KEY_ARMS}
    UNION
    -- hal_id : la clé est le premier identifiant HAL listé, comparé par égalité directe (index btree
    -- `idx_source_pubs_first_hal_id`).
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o ON {_FIRST_HAL_ID.format(a="o")} = {_FIRST_HAL_ID.format(a="d")}
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE {_FIRST_HAL_ID.format(a="d")} IS NOT NULL
    UNION
    -- Token metadata_block : même doc_type + titre + année, pour tout doc_type, titre assez long.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o
      ON o.doc_type = d.doc_type
         AND o.title_normalized = d.title_normalized
         AND o.pub_year = d.pub_year
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.doc_type IS NOT NULL
      AND length(d.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
      AND d.pub_year IS NOT NULL
""")


# Clôture du voisinage sur l'appartenance déjà matérialisée : les `source_publications` rattachées
# à la même publication qu'une SP dirty deviennent dirty à leur tour. Le voisinage 1-hop est calculé
# sur les clés **d'après** ; une SP rattachée par une clé qui vient de disparaître n'y figure plus et
# resterait sur sa publication sans être réexaminée. Marquer ces voisines plutôt que les injecter
# directement dans l'univers leur donne leur propre 1-hop, donc un rattachement correct (à la
# publication de leurs vraies voisines) plutôt qu'une publication neuve en doublon.
_SPREAD_TO_SIBLINGS_SQL = text("""
    UPDATE source_publications SET keys_dirty = true
    WHERE NOT keys_dirty
      AND publication_id IN (
          SELECT publication_id FROM source_publications
          WHERE keys_dirty AND publication_id IS NOT NULL
      )
""")


def mark_keys_dirty(conn: Connection, where: str | None = None, *, dry_run: bool = False) -> int:
    """Pose `keys_dirty = true` sur les source_publications — toutes, ou le sous-ensemble `where`.

    Outil de re-matérialisation : quand une règle de clés de confirmation change (nouveau token, seuil de garde modifié, projection revue), le stock déjà réconcilié diverge de la règle. Re-marquer `keys_dirty` fait re-réconcilier les source_publications concernées au prochain run de la phase `publications` ; sur tout le stock, c'est le *cluster-then-materialize* global. `where` est un **fragment SQL de confiance** (CLI maintenance / run_pipeline, jamais une entrée externe). `dry_run` compte sans écrire. Retourne le nombre de source_publications (marquées, ou qui le seraient).
    """
    clause = f" WHERE {where}" if where else ""
    if dry_run:
        return scalar_int(
            conn.execute(
                text(f"SELECT count(*) FROM source_publications{clause}")  # noqa: S608
            )
        )
    return conn.execute(
        text(f"UPDATE source_publications SET keys_dirty = true{clause}")  # noqa: S608
    ).rowcount


class PublicationsReconciliationQueries:
    """Requêtes de la passe de réconciliation."""

    def mark_keys_dirty(self, conn: Connection) -> int:
        """Pose `keys_dirty = true` sur toutes les `source_publications` (rebuild complet).

        Retourne le nombre de lignes marquées. Force la réconciliation à dégénérer en cluster-then-materialize global (après une évolution des règles de clés).
        """
        return mark_keys_dirty(conn)

    def mark_publication_siblings_dirty(self, conn: Connection) -> int:
        """Propage `keys_dirty` aux `source_publications` rattachées à la même publication qu'une SP déjà dirty. Retourne le nombre de lignes marquées.

        Clôt le voisinage sur l'appartenance déjà matérialisée : sans cela, une SP rattachée par une clé de confirmation qui vient de disparaître (identifiant corrigé chez la source, par exemple un DOI de préversion remplacé par celui de la version publiée) ne figure dans aucun bras du voisinage 1-hop — calculé sur les clés d'après — et resterait indéfiniment sur une publication dont plus rien ne la rapproche.
        """
        return conn.execute(_SPREAD_TO_SIBLINGS_SQL).rowcount

    def fetch_dirty_source_publication_ids(self, conn: Connection) -> list[int]:
        """Les `source_publications` `keys_dirty` (**orphelines comprises** : la réconciliation est aussi l'assignation). Seeds à réconcilier puis à nettoyer (`clear_keys_dirty`)."""
        # Orphelins **compris** : la réconciliation est aussi l'assignation (un orphelin dirty
        # se fait matcher/créer/skipper). Les source_publications traitées sont ensuite
        # nettoyées (`clear_keys_dirty`).
        rows = conn.execute(
            text("SELECT id FROM source_publications WHERE keys_dirty ORDER BY id")
        ).all()
        return [row.id for row in rows]

    def fetch_reconciliation_universe(self, conn: Connection) -> list[ReconcileRow]:
        """Le voisinage 1-hop : les SP dirty (orphelines comprises) **et** les SP qui partagent une clé de confirmation (DOI / NNT / hal_id / PMID, ou le composite thèse `title_normalized`+`pub_year`) avec l'une d'elles — matérialisées ou orphelines. Univers sur lequel tourne `connected_components`."""
        rows = conn.execute(_UNIVERSE_SQL).all()
        return [
            ReconcileRow(
                r.id,
                r.doi,
                r.external_ids,
                r.publication_id,
                r.doc_type,
                r.title_normalized,
                r.pub_year,
                r.publication_doi,
                r.in_perimeter,
            )
            for r in rows
        ]

    def fetch_publication_ids_by_doi(self, conn: Connection) -> dict[str, int]:
        """Map `lower(doi) → id` des publications existantes portant un DOI.

        Permet à `plan_reconciliation` d'ancrer un groupe sur la publication qui porte déjà son DOI même quand **aucune** SP du voisinage n'y est rattachée — publication devenue orpheline après un TRUNCATE + réimport des sources, ou dérive du `publications.doi` vis-à-vis de ses sources. Sans cela, le groupe créerait une publication neuve qui heurterait la contrainte unique sur le DOI."""
        # Map `lower(doi) → id` des publications portant un DOI. Clé sur `lower(doi)` :
        # l'index unique `publications_doi_lower_key` garantit l'unicité, et le DOI de
        # partition (`effective_doi`, via `clean_doi`) est déjà en minuscule.
        rows = conn.execute(
            text("SELECT id, lower(doi) AS doi FROM publications WHERE doi IS NOT NULL")
        ).all()
        return {row.doi: row.id for row in rows}

    def fetch_publication_sizes(
        self, conn: Connection, publication_ids: list[int]
    ) -> dict[int, int]:
        """Nombre de `source_publications` rattachées à chacune des publications `publication_ids`."""
        rows = conn.execute(
            text("""
                SELECT publication_id, count(*) AS n FROM source_publications
                WHERE publication_id = ANY(:ids) GROUP BY publication_id
            """),
            {"ids": publication_ids},
        ).all()
        return {row.publication_id: row.n for row in rows}

    def repoint_source_publications(
        self, conn: Connection, source_publication_ids: list[int], publication_id: int
    ) -> None:
        """Rattache un ensemble de `source_publications` à `publication_id` (assignation d'un groupe)."""
        if not source_publication_ids:
            return
        stmt = text(
            "UPDATE source_publications SET publication_id = :pid WHERE id = ANY(:ids)"
        ).bindparams(bindparam("ids"))
        conn.execute(stmt, {"pid": publication_id, "ids": source_publication_ids})

    def detach_source_publications(
        self, conn: Connection, source_publication_ids: list[int]
    ) -> None:
        """Détache un ensemble de `source_publications` de leur publication : elles deviennent orphelines."""
        if not source_publication_ids:
            return
        stmt = text(
            "UPDATE source_publications SET publication_id = NULL WHERE id = ANY(:ids)"
        ).bindparams(bindparam("ids"))
        conn.execute(stmt, {"ids": source_publication_ids})

    def repoint_dependents(
        self, conn: Connection, from_publication_id: int, to_publication_id: int
    ) -> None:
        """Re-pointe les paiements APC (`apc_payments`) d'une publication **dissoute** vers son successeur, et enregistre la redirection de son identifiant. À appeler avant la suppression de la publication dissoute, qui détacherait ses paiements (SET NULL)."""
        conn.execute(
            text("UPDATE apc_payments SET publication_id = :t WHERE publication_id = :s"),
            {"s": from_publication_id, "t": to_publication_id},
        )
        record_redirect(conn, MergedEntity.PUBLICATION, to_publication_id, from_publication_id)

    def mark_authorships_dirty(self, conn: Connection, publication_ids: list[int]) -> int:
        """Pose `authorships_dirty` sur ces publications. Retourne le nombre de publications marquées."""
        if not publication_ids:
            return 0
        stmt = text(
            "UPDATE publications SET authorships_dirty = true"
            " WHERE id = ANY(:ids) AND NOT authorships_dirty"
        ).bindparams(bindparam("ids"))
        return conn.execute(stmt, {"ids": publication_ids}).rowcount

    def clear_keys_dirty(self, conn: Connection, source_publication_ids: list[int]) -> int:
        """Efface `keys_dirty` sur les SP réconciliées. Retourne le nombre de lignes touchées."""
        if not source_publication_ids:
            return 0
        stmt = text(
            "UPDATE source_publications SET keys_dirty = false WHERE id = ANY(:ids)"
        ).bindparams(bindparam("ids"))
        return conn.execute(stmt, {"ids": source_publication_ids}).rowcount

    def delete_publications_without_sources(self, conn: Connection) -> int:
        """Supprime les publications auxquelles plus aucune `source_publication` n'est rattachée. Retourne le nombre de publications supprimées."""
        return conn.execute(
            text("""
                DELETE FROM publications p
                WHERE NOT EXISTS (
                    SELECT 1 FROM source_publications sp WHERE sp.publication_id = p.id
                )
            """)
        ).rowcount

    def count_publications(self, conn: Connection) -> int:
        """Total des publications (toutes in-périmètre : la réconciliation gate leur création sur le périmètre)."""
        # Toutes les publications sont in-périmètre par construction : la réconciliation gate leur création sur le périmètre.
        return int(conn.execute(text("SELECT count(*) FROM publications")).scalar_one())
