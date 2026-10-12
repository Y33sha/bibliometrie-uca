"""SQL de la phase `relations`."""

from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.publications.doc_types import DocType
from domain.source_publications.external_ids import ExternalIdType
from domain.source_publications.keys import (
    DISCRIMINANT_TITLE_MIN_LENGTH,
    SCALAR_CONFIRMATION_ID_TYPES,
)
from domain.sources.registry import Source
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.scalars import scalar_int


class DeclaredRelationSource(NamedTuple):
    """Une `source_publication` rattachée qui déclare des relations dans son `meta` (DataCite `related_identifiers` ou Crossref `relation`).

    Son DOI d'origine et son `notice_doc_type` disent si une relation de même œuvre relie deux œuvres. Le `doc_type` de sa publication type alors la relation.
    """

    publication_id: int
    source: str
    meta: dict[str, JsonValue]
    doi: str | None = None
    doc_type: str | None = None
    notice_doc_type: str | None = None


class DoiPublication(NamedTuple):
    """Une publication du corpus, désignée par un DOI qu'une relation déclarée prend pour cible."""

    id: int
    doc_type: str | None


class RelationEdge(NamedTuple):
    """Une arête de relation à persister : publication déclarante → cible, typée.

    La cible est désignée par `target_doi` (relations issues des sources, qui pointent toujours un DOI — résolu en `target_publication_id` à l'insertion) **ou** directement par `target_publication_id` (relations dérivées en interne vers une publication au corpus, qui peut ne pas avoir de DOI). Au moins l'un des deux est présent."""

    from_publication_id: int
    relation_type: str
    target_doi: str | None
    source: str
    target_publication_id: int | None = None


class SharedKeyPair(NamedTuple):
    """Deux publications distinctes partageant une clé de confirmation (hal_id, arXiv, PMID, NNT). `a_id < b_id` par construction. Le type de relation se déduit du couple de `doc_type` (`domain.publications.relations.infer_shared_key_relation`)."""

    a_id: int
    a_doc_type: str | None
    a_doi: str | None
    b_id: int
    b_doc_type: str | None
    b_doi: str | None


class TitleMatch(NamedTuple):
    """Une publication rapprochée par titre de l'œuvre dont elle dépend (signal #3) : un erratum de l'article qu'il corrige, un preprint de sa version publiée. Le parent est au corpus, désigné par son `publication_id` (et son DOI quand il en a un). `child` porte la relation dirigée vers `parent` (`is_correction_of`, `is_preprint_of`)."""

    child_id: int
    parent_id: int
    parent_doi: str | None


class RelationsRebuild(NamedTuple):
    """Ce qu'une reconstruction de `publication_relations` laisse : les arêtes écrites, celles qu'elle ajoute (par type, décroissant) et le nombre de celles qui disparaissent.

    Une arête ajoutée est présente après la reconstruction et absente avant ; une arête disparue, l'inverse. Les deux se comptent contre l'état de la table au début de la phase, pas contre le nombre d'arêtes soumises : la table est reconstruite entière à chaque run, et l'essentiel de ce qu'elle reçoit s'y trouvait déjà."""

    written: int
    added_by_type: list[tuple[str, int]]
    removed: int


# Écart d'années toléré entre une œuvre dépendante et son parent, dans les deux sens : un erratum suit son article (parent dans `[année − N … année]`), une version publiée suit son preprint (parent dans `[année … année + N]`).
_TITLE_MATCH_YEAR_WINDOW = 2

# Une ligne `pub_keys` par clé de confirmation scalaire d'`external_ids` ; `hal_id` (array) a son propre bras.
_SCALAR_KEY_ROWS = "".join(
    f"""
        UNION
        SELECT sp.publication_id, '{k}', sp.external_ids->>'{k}'
        FROM source_publications sp
        WHERE sp.publication_id IS NOT NULL AND sp.external_ids->>'{k}' IS NOT NULL"""
    for k in SCALAR_CONFIRMATION_ID_TYPES
)

# Paires de publications distinctes partageant une clé de confirmation (`source_publications.external_ids`, héritée par la publication). `k1.pid < k2.pid` produit chaque paire une fois ; le `DISTINCT` fusionne les clés multiples.
_SHARED_KEY_PAIRS_SQL = text(f"""
    WITH pub_keys AS (
        SELECT sp.publication_id AS pid, '{ExternalIdType.HAL_ID}' AS ktype, h AS kval
        FROM source_publications sp
        CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids->'{ExternalIdType.HAL_ID}') h
        WHERE sp.publication_id IS NOT NULL
          AND jsonb_typeof(sp.external_ids->'{ExternalIdType.HAL_ID}') = 'array'
        {_SCALAR_KEY_ROWS}
    )
    SELECT DISTINCT
        p1.id AS a_id, p1.doc_type AS a_doc_type, p1.doi AS a_doi,
        p2.id AS b_id, p2.doc_type AS b_doc_type, p2.doi AS b_doi
    FROM pub_keys k1
    JOIN pub_keys k2 ON k1.ktype = k2.ktype AND k1.kval = k2.kval AND k1.pid < k2.pid
    JOIN publications p1 ON p1.id = k1.pid
    JOIN publications p2 ON p2.id = k2.pid
""")

# Signal #3 — rapprochement par titre de l'œuvre dépendante (erratum, preprint) à son parent. Erratum : titre parent = suffixe du titre erratum. Preprint : titre identique. Garde d'ambiguïté : un seul candidat substantiel, sinon abstention.
_ERRATUM_TITLE_MATCHES_SQL = text(f"""
    WITH child AS (
        SELECT id, title_normalized AS t, pub_year AS y
        FROM publications
        WHERE doc_type = '{DocType.ERRATUM.value}'
          AND title_normalized IS NOT NULL AND pub_year IS NOT NULL
    ),
    candidate AS (
        SELECT c.id AS child_id, p.id AS parent_id, p.doi AS parent_doi,
               (p.doc_type::text NOT IN ('{DocType.PREPRINT.value}', '{DocType.DATASET.value}'))
                   AS substantive
        FROM child c
        JOIN publications p
          ON p.id <> c.id
         AND p.doc_type <> '{DocType.ERRATUM.value}'
         AND length(p.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
         AND p.pub_year BETWEEN c.y - {_TITLE_MATCH_YEAR_WINDOW} AND c.y
         AND right(c.t, length(p.title_normalized)) = p.title_normalized
    ),
    substantive_count AS (
        SELECT child_id, count(*) FILTER (WHERE substantive) AS n
        FROM candidate GROUP BY child_id
    )
    SELECT c.child_id, c.parent_id, c.parent_doi
    FROM candidate c
    JOIN substantive_count s ON s.child_id = c.child_id
    WHERE s.n = 1 AND c.substantive
""")

# Preprint → version publiée : titre identique, parent publié dans [année … année + 2]. Garde d'ambiguïté : un seul candidat substantiel (hors `dataset`) au même titre.
_PREPRINT_TITLE_MATCHES_SQL = text(f"""
    WITH child AS (
        SELECT id, title_normalized AS t, pub_year AS y
        FROM publications
        WHERE doc_type = '{DocType.PREPRINT.value}' AND title_normalized IS NOT NULL
          AND length(title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH} AND pub_year IS NOT NULL
    ),
    candidate AS (
        SELECT c.id AS child_id, p.id AS parent_id, p.doi AS parent_doi,
               (p.doc_type::text <> '{DocType.DATASET.value}') AS substantive
        FROM child c
        JOIN publications p
          ON p.doc_type <> '{DocType.PREPRINT.value}'
         AND p.title_normalized = c.t
         AND length(p.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
         AND p.pub_year BETWEEN c.y AND c.y + {_TITLE_MATCH_YEAR_WINDOW}
    ),
    substantive_count AS (
        SELECT child_id, count(*) FILTER (WHERE substantive) AS n
        FROM candidate GROUP BY child_id
    )
    SELECT c.child_id, c.parent_id, c.parent_doi
    FROM candidate c
    JOIN substantive_count s ON s.child_id = c.child_id
    WHERE s.n = 1 AND c.substantive
""")


class PublicationRelationsQueries:
    """Requêtes de la phase `relations`."""

    def fetch_declared_relation_sources(self, conn: Connection) -> list[DeclaredRelationSource]:
        """Les `source_publications` rattachées dont le `meta` déclare des relations."""
        # Le DOI d'origine, et non le DOI corrigé : c'est lui que la notice déclare, et c'est son
        # préfixe qui dit si une relation de même œuvre franchit un registrant.
        rows = conn.execute(
            text(f"""
                SELECT sp.publication_id, sp.source::text AS source, sp.meta,
                       lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi)) AS doi,
                       p.doc_type::text AS doc_type, sp.doc_type AS notice_doc_type
                FROM source_publications sp
                JOIN publications p ON p.id = sp.publication_id
                WHERE (sp.source = '{Source.DATACITE.value}' AND sp.meta ? 'related_identifiers')
                   OR (sp.source = '{Source.CROSSREF.value}' AND sp.meta ? 'relation')
            """)
        ).all()
        return [
            DeclaredRelationSource(
                r.publication_id, r.source, r.meta, r.doi, r.doc_type, r.notice_doc_type
            )
            for r in rows
        ]

    def fetch_publications_by_doi(
        self, conn: Connection, dois: list[str]
    ) -> dict[str, DoiPublication]:
        """Publications du corpus que désignent ces DOI, indexées par DOI en minuscules."""
        if not dois:
            return {}
        rows = conn.execute(
            text(
                "SELECT lower(doi) AS doi, id, doc_type::text AS doc_type "
                "FROM publications WHERE lower(doi) = ANY(:dois)"
            ),
            {"dois": dois},
        ).all()
        return {r.doi: DoiPublication(r.id, r.doc_type) for r in rows}

    def fetch_shared_key_pairs(self, conn: Connection) -> list[SharedKeyPair]:
        """Les paires de publications distinctes (DOI distincts) partageant une clé de confirmation (signal #2)."""
        rows = conn.execute(_SHARED_KEY_PAIRS_SQL).all()
        return [
            SharedKeyPair(r.a_id, r.a_doc_type, r.a_doi, r.b_id, r.b_doc_type, r.b_doi)
            for r in rows
        ]

    def fetch_declared_related_pairs(self, conn: Connection) -> set[frozenset[int]]:
        """Les paires déjà reliées par une relation déclarée (signal #1), pour écarter un `is_related_to` redondant."""
        rows = conn.execute(
            text(f"""
                SELECT from_publication_id AS a, target_publication_id AS b
                FROM publication_relations
                WHERE source IN ('{Source.DATACITE.value}', '{Source.CROSSREF.value}')
                  AND target_publication_id IS NOT NULL
            """)
        ).all()
        return {frozenset((r.a, r.b)) for r in rows}

    def fetch_erratum_title_matches(self, conn: Connection) -> list[TitleMatch]:
        """Les erratums rapprochés par titre de l'œuvre qu'ils corrigent (signal #3).

        Pour chaque erratum, candidats = publications non-erratum, titre assez long, publiées dans la fenêtre `[année − 2 … année]`, dont le `title_normalized` est un suffixe de celui de l'erratum (le titre parent est reproduit verbatim après un préfixe « Erratum: »). Garde d'ambiguïté : on ne rapproche que si **exactement un** candidat « substantiel » (hors `preprint` et `dataset`, simples formes de la même œuvre) porte ce titre."""
        rows = conn.execute(_ERRATUM_TITLE_MATCHES_SQL).all()
        return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]

    def fetch_preprint_title_matches(self, conn: Connection) -> list[TitleMatch]:
        """Les preprints rapprochés par titre de leur version publiée (signal #3).

        Pour chaque preprint, candidats = publications non-preprint au `title_normalized` **identique** (le preprint et sa version publiée portent le même titre), titre assez long, publiées dans la fenêtre `[année … année + 2]`. Même garde d'ambiguïté : un seul candidat substantiel (hors `dataset`) au même titre."""
        rows = conn.execute(_PREPRINT_TITLE_MATCHES_SQL).all()
        return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]

    # Colonnes qui identifient une arête, celles de la contrainte d'unicité : deux arêtes qui s'y
    # accordent sont le même lien. Le diff avant/après les compare.
    _IDENTITE = "from_publication_id, relation_type, target_publication_id, target_doi"

    def rebuild_relations(self, conn: Connection, edges: list[RelationEdge]) -> RelationsRebuild:
        """Reconstruit `publication_relations` : purge la table, puis insère `edges` (chaque arête portant sa `source`). Résout les `target_doi` en `target_publication_id`, écarte les auto-relations, dédoublonne par `(from, type, target)` — l'ordre de `edges` fixe la priorité. Retourne ce que la reconstruction a écrit et changé."""
        # La table temporaire vit le temps de l'appel : créée avant la purge, elle sert le diff puis
        # disparaît. Un échec en cours de route annule sa création avec le reste de la transaction.
        conn.execute(
            text(
                f"CREATE TEMP TABLE relations_avant AS "
                f"SELECT {self._IDENTITE} FROM publication_relations"
            )
        )
        conn.execute(text("DELETE FROM publication_relations"))
        written = 0 if not edges else self._insert_edges(conn, edges)
        rebuild = RelationsRebuild(written, self._count_added(conn), self._count_removed(conn))
        conn.execute(text("DROP TABLE relations_avant"))
        return rebuild

    def _count_added(self, conn: Connection) -> list[tuple[str, int]]:
        """Arêtes présentes après la reconstruction et absentes avant, par type."""
        rows = conn.execute(
            text(f"""
                SELECT relation_type::text AS rel_type, count(*) AS cnt
                FROM (
                    SELECT {self._IDENTITE} FROM publication_relations
                    EXCEPT
                    SELECT {self._IDENTITE} FROM relations_avant
                ) ajoutees
                GROUP BY relation_type
                ORDER BY cnt DESC
            """)
        ).all()
        return [(r.rel_type, r.cnt) for r in rows]

    def _count_removed(self, conn: Connection) -> int:
        """Arêtes présentes avant la reconstruction et absentes après."""
        return scalar_int(
            conn.execute(
                text(f"""
                    SELECT count(*) FROM (
                        SELECT {self._IDENTITE} FROM relations_avant
                        EXCEPT
                        SELECT {self._IDENTITE} FROM publication_relations
                    ) disparues
                """)
            )
        )

    def _insert_edges(self, conn: Connection, edges: list[RelationEdge]) -> int:
        payload = [
            {
                "f": e.from_publication_id,
                "t": e.relation_type,
                "d": e.target_doi,
                "p": e.target_publication_id,
                "s": e.source,
            }
            for e in edges
        ]
        stmt = text("""
            INSERT INTO publication_relations
                (from_publication_id, relation_type, target_doi, target_publication_id, source)
            SELECT e.f, e.t::relation_type, e.d, COALESCE(e.p, p.id), e.s
            FROM jsonb_to_recordset(:payload) AS e(f int, t text, d text, p int, s text)
            LEFT JOIN publications p ON e.p IS NULL AND e.d IS NOT NULL AND lower(p.doi) = e.d
            WHERE COALESCE(e.p, p.id) IS NULL OR COALESCE(e.p, p.id) <> e.f
            ON CONFLICT ON CONSTRAINT publication_relations_uq DO NOTHING
        """).bindparams(bindparam("payload", type_=Jsonb))
        return conn.execute(stmt, {"payload": payload}).rowcount

    def count_by_relation_type(self, conn: Connection) -> list[tuple[str, int]]:
        """`(relation_type, nombre)` par type, décroissant — distribution de `publication_relations`."""
        # Alias `rel_type` / `cnt` : nommer une colonne `t` heurterait l'attribut déprécié `Row.t` de SQLAlchemy (`r.t` renverrait la Row entière, non la colonne).
        rows = conn.execute(
            text(
                "SELECT relation_type::text AS rel_type, count(*) AS cnt FROM publication_relations "
                "GROUP BY relation_type ORDER BY cnt DESC"
            )
        ).all()
        return [(r.rel_type, r.cnt) for r in rows]
