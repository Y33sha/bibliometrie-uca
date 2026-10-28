"""Phase `relations` — population de `publication_relations` depuis les relations déclarées.

Tourne après `publications` : les `source_records` sont rattachées à leur publication canonique, et les DOI cibles sont résolus en `publication_id` quand ils sont au corpus.

Trois signaux peuplent la table :

- **Signal #1 — relations déclarées par les sources** : DataCite `source_extras.related_identifiers` et Crossref `source_extras.relation`, converties vers le vocabulaire canonique par `domain.publications.relations`.
- **Signal #2 — clés de confirmation partagées** : deux publications distinctes qui partagent une clé (hal_id, arXiv, PMID, NNT) sont apparentées ; le type se déduit de leur couple de `doc_type` (`infer_shared_key_relation`).
- **Signal #3 — rapprochement par titre** : une publication dépendante sans relation déclarée ni clé partagée est reliée à l'œuvre dont elle dépend par le titre — un erratum à l'article qu'il corrige (`is_correction_of`, titre parent en suffixe après « Erratum: »…), un preprint à sa version publiée (`is_preprint_of`, titre identique). Sous garde d'ambiguïté (un seul parent substantiel au même titre). La sélection et sa garde sont en SQL.

Les relations de même œuvre (versions, formes variantes, pièces de package) relèvent de la déduplication, à la phase `metadata_correction`. Quand `IsVersionOf` ou `IsVariantFormOf` relient deux œuvres (cf. `meme_oeuvre_declaree`), le signal #1 les type par leur couple de `doc_type`, comme un preprint arXiv et l'article publié.

Reconstruction complète à chaque run (table dérivée) : la table est purgée puis réécrite depuis les trois signaux réunis, en une transaction — idempotent et sans dérive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.publications.doc_types import DocType
from domain.publications.identifiers import clean_doi
from domain.publications.relations import (
    DEPENDENT_DOC_TYPE_RELATIONS,
    RELATION_PAIR_LABELS,
    RelationType,
    extract_crossref_relations,
    extract_datacite_distinct_works,
    extract_datacite_relations,
    infer_shared_key_relation,
)
from domain.source_records.identifiers import SourceIdentifierType
from domain.source_records.keys import (
    CONFIRMATION_ID_TYPES,
    DISCRIMINANT_TITLE_MIN_LENGTH,
)
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import Source
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.scalars import scalar_int
from infrastructure.db.source_record_identifiers import first_of_its_type_sql
from infrastructure.sql_fragments import has_source_extra, in_clause, raw_column
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import (
    LAST_BRANCH,
    breakdown,
    inflect,
    quantity,
    step,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks


class DeclaredRelationSource(NamedTuple):
    """Une `source_record` rattachée qui déclare des relations dans son `source_extras` (DataCite `related_identifiers` ou Crossref `relation`).

    Son DOI d'origine et son `source_record_doc_type` disent si une relation de même œuvre relie deux œuvres. Le `doc_type` de sa publication type alors la relation.
    """

    publication_id: int
    source: str
    source_extras: dict[str, JsonValue]
    doi: str | None = None
    doc_type: str | None = None
    source_record_doc_type: str | None = None


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

# Types de clé dont chaque enregistrement source retient une seule valeur (`confirmation_identifiers`).
_SINGLE_KEY_TYPES = tuple(
    str(t) for t in CONFIRMATION_ID_TYPES if t is not SourceIdentifierType.HAL_ID
)

# Paires de publications distinctes partageant une clé de confirmation, héritée par la publication de ses enregistrements sources : tout `hal_id` actif, et pour NNT, PMID et arXiv l'identifiant actif de rôle le plus fort, puis de plus petite valeur. `k1.pid < k2.pid` produit chaque paire une fois ; le `DISTINCT` fusionne les clés multiples.
_SHARED_KEY_PAIRS_SQL = text(f"""
    WITH pub_keys AS (
        SELECT sr.publication_id AS pid, i.id_type::text AS ktype, i.id_value AS kval
        FROM source_records sr
        JOIN source_record_identifiers i ON i.source_record_id = sr.id
        WHERE sr.publication_id IS NOT NULL
          AND (
              (i.id_type = '{SourceIdentifierType.HAL_ID}' AND i.removed_by IS NULL)
              OR (i.id_type::text IN {in_clause(_SINGLE_KEY_TYPES)}
                  AND {first_of_its_type_sql("i")})
          )
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
        SELECT id, title_normalized AS t, publication_year AS y
        FROM publications
        WHERE doc_type = '{DocType.ERRATUM.value}'
          AND title_normalized IS NOT NULL AND publication_year IS NOT NULL
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
         AND p.publication_year BETWEEN c.y - {_TITLE_MATCH_YEAR_WINDOW} AND c.y
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
        SELECT id, title_normalized AS t, publication_year AS y
        FROM publications
        WHERE doc_type = '{DocType.PREPRINT.value}' AND title_normalized IS NOT NULL
          AND length(title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH} AND publication_year IS NOT NULL
    ),
    candidate AS (
        SELECT c.id AS child_id, p.id AS parent_id, p.doi AS parent_doi,
               (p.doc_type::text <> '{DocType.DATASET.value}') AS substantive
        FROM child c
        JOIN publications p
          ON p.doc_type <> '{DocType.PREPRINT.value}'
         AND p.title_normalized = c.t
         AND length(p.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
         AND p.publication_year BETWEEN c.y AND c.y + {_TITLE_MATCH_YEAR_WINDOW}
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


def fetch_declared_relation_sources(conn: Connection) -> list[DeclaredRelationSource]:
    """Les `source_records` rattachées dont le `source_extras` déclare des relations."""
    # Le DOI d'origine, et non le DOI corrigé : c'est lui que l'enregistrement source déclare, et c'est son
    # préfixe qui dit si une relation de même œuvre franchit un registrant.
    rows = conn.execute(
        text(f"""
            SELECT sr.publication_id, sr.source::text AS source, sr.source_extras,
                   lower({raw_column("doi")}) AS doi,
                   p.doc_type::text AS doc_type, sr.doc_type AS source_record_doc_type
            FROM source_records sr
            JOIN publications p ON p.id = sr.publication_id
            WHERE (sr.source = '{Source.DATACITE.value}' AND {has_source_extra(SourceExtra.RELATED_IDENTIFIERS)})
               OR (sr.source = '{Source.CROSSREF.value}' AND {has_source_extra(SourceExtra.RELATION)})
        """)
    ).all()
    return [
        DeclaredRelationSource(
            r.publication_id,
            r.source,
            r.source_extras,
            r.doi,
            r.doc_type,
            r.source_record_doc_type,
        )
        for r in rows
    ]


def fetch_publications_by_doi(conn: Connection, dois: list[str]) -> dict[str, DoiPublication]:
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


def fetch_shared_key_pairs(conn: Connection) -> list[SharedKeyPair]:
    """Les paires de publications distinctes (DOI distincts) partageant une clé de confirmation (signal #2)."""
    rows = conn.execute(_SHARED_KEY_PAIRS_SQL).all()
    return [
        SharedKeyPair(r.a_id, r.a_doc_type, r.a_doi, r.b_id, r.b_doc_type, r.b_doi) for r in rows
    ]


def fetch_erratum_title_matches(conn: Connection) -> list[TitleMatch]:
    """Les erratums rapprochés par titre de l'œuvre qu'ils corrigent (signal #3).

    Pour chaque erratum, candidats = publications non-erratum, titre assez long, publiées dans la fenêtre `[année − 2 … année]`, dont le `title_normalized` est un suffixe de celui de l'erratum (le titre parent est reproduit verbatim après un préfixe « Erratum: »). Garde d'ambiguïté : on ne rapproche que si **exactement un** candidat « substantiel » (hors `preprint` et `dataset`, simples formes de la même œuvre) porte ce titre."""
    rows = conn.execute(_ERRATUM_TITLE_MATCHES_SQL).all()
    return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]


def fetch_preprint_title_matches(conn: Connection) -> list[TitleMatch]:
    """Les preprints rapprochés par titre de leur version publiée (signal #3).

    Pour chaque preprint, candidats = publications non-preprint au `title_normalized` **identique** (le preprint et sa version publiée portent le même titre), titre assez long, publiées dans la fenêtre `[année … année + 2]`. Même garde d'ambiguïté : un seul candidat substantiel (hors `dataset`) au même titre."""
    rows = conn.execute(_PREPRINT_TITLE_MATCHES_SQL).all()
    return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]


# Colonnes qui identifient une arête, celles de la contrainte d'unicité : deux arêtes qui s'y
# accordent sont le même lien. Le diff avant/après les compare.
_IDENTITY_COLUMNS = "from_publication_id, relation_type, target_publication_id, target_doi"


def rebuild_relations(conn: Connection, edges: list[RelationEdge]) -> RelationsRebuild:
    """Reconstruit `publication_relations` : purge la table, puis insère `edges` (chaque arête portant sa `source`). Résout les `target_doi` en `target_publication_id`, écarte les auto-relations, dédoublonne par `(from, type, target)` — l'ordre de `edges` fixe la priorité. Retourne ce que la reconstruction a écrit et changé."""
    # La table temporaire vit le temps de l'appel : créée avant la purge, elle sert le diff puis
    # disparaît. Un échec en cours de route annule sa création avec le reste de la transaction.
    conn.execute(
        text(
            f"CREATE TEMP TABLE relations_before AS "
            f"SELECT {_IDENTITY_COLUMNS} FROM publication_relations"
        )
    )
    conn.execute(text("DELETE FROM publication_relations"))
    written = 0 if not edges else _insert_edges(conn, edges)
    rebuild = RelationsRebuild(written, _count_added(conn), _count_removed(conn))
    conn.execute(text("DROP TABLE relations_before"))
    return rebuild


def _count_added(conn: Connection) -> list[tuple[str, int]]:
    """Arêtes présentes après la reconstruction et absentes avant, par type."""
    rows = conn.execute(
        text(f"""
            SELECT relation_type::text AS rel_type, count(*) AS cnt
            FROM (
                SELECT {_IDENTITY_COLUMNS} FROM publication_relations
                EXCEPT
                SELECT {_IDENTITY_COLUMNS} FROM relations_before
            ) added
            GROUP BY relation_type
            ORDER BY cnt DESC
        """)
    ).all()
    return [(r.rel_type, r.cnt) for r in rows]


def _count_removed(conn: Connection) -> int:
    """Arêtes présentes avant la reconstruction et absentes après."""
    return scalar_int(
        conn.execute(
            text(f"""
                SELECT count(*) FROM (
                    SELECT {_IDENTITY_COLUMNS} FROM relations_before
                    EXCEPT
                    SELECT {_IDENTITY_COLUMNS} FROM publication_relations
                ) removed
            """)
        )
    )


def _insert_edges(conn: Connection, edges: list[RelationEdge]) -> int:
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


def count_by_relation_type(conn: Connection) -> list[tuple[str, int]]:
    """`(relation_type, nombre)` par type, décroissant — distribution de `publication_relations`."""
    # Alias `rel_type` / `cnt` : nommer une colonne `t` heurterait l'attribut déprécié `Row.t` de SQLAlchemy (`r.t` renverrait la Row entière, non la colonne).
    rows = conn.execute(
        text(
            "SELECT relation_type::text AS rel_type, count(*) AS cnt FROM publication_relations "
            "GROUP BY relation_type ORDER BY cnt DESC"
        )
    ).all()
    return [(r.rel_type, r.cnt) for r in rows]


def _build_declared_edges(sources: list[DeclaredRelationSource]) -> list[RelationEdge]:
    edges: list[RelationEdge] = []
    for source_record in sources:
        if source_record.source == "datacite":
            relations = extract_datacite_relations(source_record.source_extras)
        elif source_record.source == "crossref":
            relations = extract_crossref_relations(source_record.source_extras)
        else:
            continue
        edges.extend(
            RelationEdge(
                source_record.publication_id, rel_type.value, target_doi, source_record.source
            )
            for rel_type, target_doi in relations
        )
    return edges


def _distinct_work_targets(sources: list[DeclaredRelationSource]) -> list[str]:
    """DOI que les enregistrements sources DataCite déclarent comme autre forme de leur œuvre, chez un autre registrant."""
    return sorted(
        {
            doi
            for source_record in sources
            if source_record.source == "datacite"
            for doi in extract_datacite_distinct_works(
                source_record.source_extras, source_record.doi, source_record.source_record_doc_type
            )
        }
    )


def _build_distinct_work_edges(
    sources: list[DeclaredRelationSource], publications_by_doi: dict[str, DoiPublication]
) -> list[RelationEdge]:
    """Relie un enregistrement source DataCite à la forme d'un autre registrant qu'il déclare de la même œuvre.

    Le type se déduit du couple de `doc_type`, comme pour une clé partagée : un preprint face à l'article publié donne `is_preprint_of`. Une cible absente du corpus a un type inconnu : face à elle, un preprint donne `is_preprint_of`, les autres enregistrements sources `is_related_to`.
    """
    edges: list[RelationEdge] = []
    for source_record in sources:
        if source_record.source != "datacite":
            continue
        for target_doi in extract_datacite_distinct_works(
            source_record.source_extras, source_record.doi, source_record.source_record_doc_type
        ):
            target = publications_by_doi.get(target_doi)
            inferred = infer_shared_key_relation(
                source_record.doc_type, target.doc_type if target else None
            )
            if inferred is None:
                continue
            relation, subject = inferred
            if subject == "b":
                # Une cible typée est au corpus : c'est elle qui porte la relation dirigée.
                assert target is not None
                edges.append(
                    RelationEdge(
                        target.id,
                        relation.value,
                        source_record.doi,
                        "datacite",
                        target_publication_id=source_record.publication_id,
                    )
                )
            else:
                edges.append(
                    RelationEdge(
                        source_record.publication_id, relation.value, target_doi, "datacite"
                    )
                )
    return edges


def _declared_pairs(
    edges: list[RelationEdge], publications_by_doi: dict[str, DoiPublication]
) -> set[frozenset[int]]:
    """Paires de publications que relient les relations déclarées (signal #1), la cible résolue par son DOI."""
    pairs: set[frozenset[int]] = set()
    for edge in edges:
        target = edge.target_publication_id
        if target is None and edge.target_doi is not None:
            resolved = publications_by_doi.get(edge.target_doi)
            target = resolved.id if resolved else None
        if target is not None:
            pairs.add(frozenset((edge.from_publication_id, target)))
    return pairs


def _build_shared_key_edges(
    pairs: list[SharedKeyPair], declared_pairs: set[frozenset[int]]
) -> list[RelationEdge]:
    """Une arête dirigée par paire partageant une clé. La cible est désignée par son `publication_id`, avec son DOI quand elle en a un. `infer_shared_key_relation` donne le type et le sujet (`"a"`, `"b"`, ou `"sym"` symétrique — orienté depuis A, le plus petit id). Les paires hors scope (peer-review) sont écartées, ainsi que les `is_related_to` (type vague « à qualifier ») sur une paire déjà typée précisément par le signal #1 — sinon doublon redondant."""
    edges: list[RelationEdge] = []
    for pair in pairs:
        inferred = infer_shared_key_relation(pair.a_doc_type, pair.b_doc_type)
        if inferred is None:
            continue
        relation, subject = inferred
        if (
            relation is RelationType.IS_RELATED_TO
            and frozenset((pair.a_id, pair.b_id)) in declared_pairs
        ):
            continue
        if subject == "b":
            from_id, target_id, target_doi = pair.b_id, pair.a_id, pair.a_doi
        else:  # "a" ou "sym" : A est le sujet (a_id < b_id rend l'orientation stable)
            from_id, target_id, target_doi = pair.a_id, pair.b_id, pair.b_doi
        edges.append(
            RelationEdge(
                from_id,
                relation.value,
                clean_doi(target_doi) if target_doi else None,
                "shared_key",
                target_publication_id=target_id,
            )
        )
    return edges


def _build_title_match_edges(
    matches: list[TitleMatch], relation_type: RelationType
) -> list[RelationEdge]:
    """Une arête `enfant relation_type parent` par rapprochement de titre. La cible est désignée par le `publication_id` du parent (au corpus), avec son DOI quand il en a un — l'unicité dédoublonne alors contre une éventuelle relation déjà posée vers ce même parent par un autre signal."""
    return [
        RelationEdge(
            match.child_id,
            relation_type.value,
            clean_doi(match.parent_doi) if match.parent_doi else None,
            "title_match",
            target_publication_id=match.parent_id,
        )
        for match in matches
    ]


@dataclass(frozen=True)
class RelationsPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute la tâche `relations.rebuild`."""
        return run_tasks("relations", {"relations.rebuild": TaskStep(self._rebuild)}, ctx)[
            "relations.rebuild"
        ]

    def _rebuild(self, ctx: PhaseContext) -> PhaseMetrics:
        """Reconstruit `publication_relations` depuis les trois signaux, en une transaction, et retourne les compteurs de la phase (répartition par type de relation dans `details`)."""
        with ctx.open_tx() as conn:
            sources = fetch_declared_relation_sources(conn)
            declared_edges = _build_declared_edges(sources)
            publications_by_doi = fetch_publications_by_doi(
                conn,
                sorted(
                    {
                        *_distinct_work_targets(sources),
                        *(edge.target_doi for edge in declared_edges if edge.target_doi),
                    }
                ),
            )
            declared_edges += _build_distinct_work_edges(sources, publications_by_doi)

            pairs = fetch_shared_key_pairs(conn)
            shared_edges = _build_shared_key_edges(
                pairs, _declared_pairs(declared_edges, publications_by_doi)
            )

            erratum_matches = fetch_erratum_title_matches(conn)
            preprint_matches = fetch_preprint_title_matches(conn)
            title_edges = _build_title_match_edges(
                erratum_matches, DEPENDENT_DOC_TYPE_RELATIONS["erratum"]
            ) + _build_title_match_edges(preprint_matches, DEPENDENT_DOC_TYPE_RELATIONS["preprint"])

            # L'ordre déclarées → clés partagées → titre fixe la priorité de dédup (`ON CONFLICT`).
            rebuild = rebuild_relations(conn, declared_edges + shared_edges + title_edges)
            by_type = count_by_relation_type(conn)

        _log_changes(rebuild, ctx.logger)

        metrics = PhaseMetrics()
        metrics.add(new=sum(count for _, count in rebuild.added_by_type))
        metrics.details["table"] = {
            "rows": [{"key": relation_type, "count": count} for relation_type, count in by_type]
        }
        return metrics


def _log_changes(rebuild: RelationsRebuild, logger: logging.Logger) -> None:
    """Écrit ce que la reconstruction a changé : les relations ajoutées par nature du lien, puis celles qui ont disparu.

    La table étant reconstruite entière à chaque run, le nombre d'arêtes écrites ne dit rien : presque toutes s'y trouvaient déjà. Seul l'écart avec l'état précédent porte une information.
    """
    added = _count_by_pair_label(rebuild.added_by_type)
    total = sum(added.values())
    step(logger, "Relations entre publications")
    if total:
        breakdown(
            logger,
            f"{quantity(total, 'nouvelle relation', 'nouvelles relations')}, dont",
            ((count, label) for label, count in added.items()),
            last=not rebuild.removed,
        )
    if rebuild.removed:
        logger.info(
            "%s%s %s",
            LAST_BRANCH,
            quantity(rebuild.removed, "relation"),
            inflect(rebuild.removed, "retirée"),
        )
    elif not total:
        logger.info("%saucun changement", LAST_BRANCH)


def _count_by_pair_label(added_by_type: list[tuple[str, int]]) -> dict[str, int]:
    """Regroupe les compteurs par nature du lien : un type et son inverse désignent le même."""
    by_label: dict[str, int] = {}
    for relation_type, count in added_by_type:
        label = RELATION_PAIR_LABELS.get(RelationType(relation_type), relation_type)
        by_label[label] = by_label.get(label, 0) + count
    return dict(sorted(by_label.items(), key=lambda item: item[1], reverse=True))


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return RelationsPhase()
