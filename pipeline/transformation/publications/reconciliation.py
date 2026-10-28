"""Passe d'assignation + réconciliation des composantes — match/create/skip **et** merge/split unifiés.

Recalcule les composantes connexes du voisinage 1-hop des `source_records` de la file `source_record_keys_queue` et assigne chaque enregistrement source à la publication ancre de sa partition `(composante ∩ DOI)`. Assignation d'un orphelin (match/create/skip) et réconciliation de publications matérialisées (merge/split) sont des facettes du même primitif. La décision revient à `domain.publications.reconciliation.plan_reconciliation` (pure) ; ce module l'applique :

- **groupes** : les enregistrements sources de chaque groupe sont rattachés à son ancre (publication existante conservée), ou à une publication créée quand la partition est sans ancre existante (split) ;
- **publications dissoutes** (vidées de tous leurs enregistrements sources par un merge) : `lifecycle.dissolve` redirige leurs paiements APC et leur identifiant vers le successeur, puis les supprime ;
- **rafraîchissement** : `lifecycle.refresh` recalcule les métadonnées consolidées de chaque publication d'un enregistrement source relevé, avant comme après la réconciliation, et de chaque publication cible d'un groupe. Il supprime celles restées sans source.

Les `contributions` sont laissées à la phase `contributions` (`insert_missing` + `prune_orphan`, set-based) — la réconciliation gère l'appartenance des enregistrements sources et les métadonnées des publications, et laisse les contributions.

Voisinage 1-hop, pas de fermeture transitive : l'invariant du marquage garantit que toute arête neuve a une extrémité marquée (raisonnement détaillé dans `domain/publications/reconciliation.py`). La passe s'ouvre sur le marquage des enregistrements sources co-rattachés à une publication avec un enregistrement source marqué, qui clôt le voisinage sur les arêtes **retirées** autant que sur les neuves.

`reconcile_source_records` applique la même passe à une liste d'enregistrements sources, hors de la file : l'administration l'appelle après une fusion manuelle.

Tâche `publications.reconcile`.
"""

import logging
import time
from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.publications.reconciliation import (
    ReconcileMember,
    ReconcilePlan,
    WorkGroup,
    manual_merge_tokens,
    plan_reconciliation,
)
from domain.source_records.identifiers import SourceIdentifier, SourceIdentifierRole
from domain.source_records.keys import (
    CONFIRMATION_ID_TYPES,
    DISCRIMINANT_TITLE_MIN_LENGTH,
    project_confirmation_keys,
)
from infrastructure.db.queues import Queue, delete_processed, enqueue, snapshot
from infrastructure.db.savepoint import savepoint
from infrastructure.db.scalars import scalar_int
from infrastructure.db.source_record_identifiers import identifiers_json_sql, parse_identifiers
from infrastructure.sql_fragments import case_priority, in_clause
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
    step,
)
from pipeline.runtime.observability.progress import track_progress, waiting
from pipeline.transformation.publications import lifecycle

# ─── SQL ─────────────────────────────────────────────────────────


class ReconcileRow(NamedTuple):
    """Projection d'une `source_record` du voisinage : clés + publication courante.

    `doc_type`/`title_normalized`/`publication_year` alimentent le token métadonnée de `project_confirmation_keys` (les identifiants viennent de `doi`/`identifiers`).
    `publication_id` = `None` si orpheline ; `is_matchable` = l'enregistrement source entre dans la réconciliation ; `publication_doi` = DOI de la publication courante (`None` si orpheline), pour choisir l'ancre ; `in_perimeter` = l'enregistrement source a ≥1 contribution source in-périmètre (gate de création d'une publication neuve) ; `manual_merge_ids` = fusions manuelles qui désignent l'enregistrement source."""

    id: int
    doi: str | None
    identifiers: tuple[SourceIdentifier, ...]
    publication_id: int | None
    doc_type: str | None
    title_normalized: str | None
    publication_year: int | None
    is_matchable: bool
    publication_doi: str | None
    in_perimeter: bool
    manual_merge_ids: list[int]


# Relevé de la file `source_record_keys_queue`.
_SNAPSHOT = "source_record_keys_marks"

# Voisinage 1-hop : les `source_records` relevées dans la file (orphelines comprises) et celles qui
# partagent une clé de confirmation avec elles. Une branche UNION par type de clé (chacune
# annotée en ligne). `publication_doi` (via LEFT JOIN) choisit l'ancre ; `in_perimeter`
# (EXISTS) gate la création d'une publication neuve pour une partition d'orphelins.
_COLS = (
    "{a}.id, {a}.doi, " + identifiers_json_sql("{a}.id") + " AS identifiers, {a}.publication_id, "
    "{a}.doc_type, {a}.title_normalized, {a}.publication_year, {a}.is_matchable, "
    "p.doi AS publication_doi, "
    "EXISTS (SELECT 1 FROM source_contributions sc "
    "WHERE sc.source_record_id = {a}.id AND sc.in_perimeter) AS in_perimeter, "
    "ARRAY(SELECT mm.manual_merge_id FROM manual_merge_source_records mm "
    "WHERE mm.source = {a}.source AND mm.source_id = {a}.source_id "
    "ORDER BY mm.manual_merge_id) AS manual_merge_ids"
)

# Rang d'un rôle d'identifiant, dans l'ordre de `SourceIdentifierRole`.
_ROLE_RANK = case_priority(tuple(SourceIdentifierRole), "{a}.role")

# L'identifiant aliasé `{a}` de `source_record_identifiers` est la clé de confirmation de son type
# (`confirmation_identifiers`) : actif, et premier des identifiants actifs de son type dans
# l'enregistrement source, par rôle puis par valeur. La collation `C` compare les valeurs comme Python.
_CONFIRMATION_KEY_SQL = (
    "{a}.removed_by IS NULL AND {a}.id_type::text IN "
    + in_clause(tuple(map(str, CONFIRMATION_ID_TYPES)))
    + " AND NOT EXISTS (SELECT 1 FROM source_record_identifiers x"
    " WHERE x.source_record_id = {a}.source_record_id AND x.id_type = {a}.id_type"
    " AND x.removed_by IS NULL AND ("
    + _ROLE_RANK.format(a="x")
    + ', x.id_value COLLATE "C") < ('
    + _ROLE_RANK
    + ', {a}.id_value COLLATE "C"))'
)

_UNIVERSE_SQL = text(f"""
    WITH dirty AS (
        SELECT {_COLS.format(a="sr")}
        FROM {_SNAPSHOT} m
        JOIN source_records sr ON sr.id = m.id
        LEFT JOIN publications p ON p.id = sr.publication_id
    )
    SELECT id, doi, identifiers, publication_id, doc_type, title_normalized, publication_year,
           is_matchable, publication_doi, in_perimeter, manual_merge_ids
    FROM dirty
    UNION
    -- DOI : égalité directe (la colonne est toujours normalisée minuscule par `clean_doi` à
    -- l'écriture), pour utiliser l'index btree `idx_source_records_doi` plutôt qu'un scan via `lower()`.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_records o ON o.doi IS NOT NULL AND o.doi = d.doi
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.doi IS NOT NULL
    UNION
    -- Identifiants : même type et même valeur, clé de confirmation de part et d'autre (index
    -- `idx_source_record_identifiers_value`).
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_record_identifiers di
      ON di.source_record_id = d.id AND {_CONFIRMATION_KEY_SQL.format(a="di")}
    JOIN source_record_identifiers oi
      ON oi.id_type = di.id_type AND oi.id_value = di.id_value
         AND {_CONFIRMATION_KEY_SQL.format(a="oi")}
    JOIN source_records o ON o.id = oi.source_record_id
    LEFT JOIN publications p ON p.id = o.publication_id
    UNION
    -- Token metadata_block : même doc_type + titre + année, pour tout doc_type, titre assez long.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_records o
      ON o.doc_type = d.doc_type
         AND o.title_normalized = d.title_normalized
         AND o.publication_year = d.publication_year
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.doc_type IS NOT NULL
      AND length(d.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
      AND d.publication_year IS NOT NULL
    UNION
    -- Fusion manuelle : les enregistrements sources désignés par une même fusion manuelle.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN manual_merge_source_records m ON m.manual_merge_id = ANY(d.manual_merge_ids)
    JOIN source_records o ON o.source = m.source AND o.source_id = m.source_id
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE cardinality(d.manual_merge_ids) > 0
""")


# Clôture du voisinage sur l'appartenance déjà matérialisée : les `source_records` rattachées
# à la même publication qu'un enregistrement source en file entrent en file à leur tour. Le voisinage 1-hop est calculé
# sur les clés courantes : un enregistrement source rattaché par une clé disparue en est absent, et resterait sur sa
# publication sans être réexaminé. Marquées, ces voisines obtiennent leur propre 1-hop, donc
# un rattachement à la publication de leurs vraies voisines, sans publication en doublon.
_SIBLINGS_SQL = f"""
    SELECT o.id FROM source_records o
    WHERE o.publication_id IN (
        SELECT sr.publication_id FROM {Queue.SOURCE_RECORD_KEYS} q
        JOIN source_records sr ON sr.id = q.id
        WHERE sr.publication_id IS NOT NULL
    )
      AND NOT EXISTS (SELECT 1 FROM {Queue.SOURCE_RECORD_KEYS} q WHERE q.id = o.id)
"""  # noqa: S608


def mark_for_reconciliation(
    conn: Connection, where: str | None = None, *, dry_run: bool = False
) -> int:
    """Marque pour la réconciliation les source_records — toutes, ou le sous-ensemble `where`.

    Outil de re-matérialisation : quand une règle de clés de confirmation change (token, seuil de garde, projection), le stock déjà réconcilié diverge de la règle. Les source_records marquées sont re-réconciliées au prochain run de la phase `publications` ; sur tout le stock, c'est le *cluster-then-materialize* global. `where` est un **fragment SQL de confiance** (CLI maintenance / run_pipeline, jamais une entrée externe). `dry_run` compte sans écrire. Retourne le nombre de source_records (marquées, ou qui le seraient).
    """
    clause = f" WHERE {where}" if where else ""
    if dry_run:
        return scalar_int(
            conn.execute(
                text(f"SELECT count(*) FROM source_records{clause}")  # noqa: S608
            )
        )
    return enqueue(conn, Queue.SOURCE_RECORD_KEYS, f"SELECT id FROM source_records{clause}", {})


def mark_publication_siblings(conn: Connection) -> int:
    """Marque pour la réconciliation les `source_records` rattachés à la même publication qu'un enregistrement source en file. Retourne le nombre de lignes marquées.

    Clôt le voisinage sur l'appartenance déjà matérialisée. Un enregistrement source rattaché par une clé de confirmation disparue (identifiant corrigé chez la source, par exemple un DOI de préversion remplacé par celui de la version publiée) est absent du voisinage 1-hop, calculé sur les clés courantes : marqué, il est réexaminé.
    """
    return enqueue(conn, Queue.SOURCE_RECORD_KEYS, _SIBLINGS_SQL, {})


def snapshot_queued_source_records(conn: Connection) -> list[int]:
    """Relève la file des `source_records` à réconcilier, orphelines comprises : la réconciliation est aussi l'assignation. Rend les identifiants de celles qui existent. `delete_processed_marks` retire de la file tous les marquages relevés."""
    snapshot(conn, Queue.SOURCE_RECORD_KEYS, _SNAPSHOT)
    return list(
        conn.execute(
            text(
                f"SELECT m.id FROM {_SNAPSHOT} m"  # noqa: S608
                " JOIN source_records sr ON sr.id = m.id ORDER BY m.id"
            )
        ).scalars()
    )


def snapshot_source_records(conn: Connection, source_record_ids: Sequence[int]) -> None:
    """Relève les enregistrements sources `source_record_ids` et ceux rattachés à leurs publications, dans la table du relevé de la file. La file reste intacte."""
    conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{_SNAPSHOT}"))
    conn.execute(
        text(f"""
            CREATE TEMP TABLE {_SNAPSHOT} AS
            SELECT id FROM source_records WHERE id = ANY(:ids)
            UNION
            SELECT o.id FROM source_records o
            WHERE o.publication_id IN (
                SELECT publication_id FROM source_records WHERE id = ANY(:ids)
            )
        """),  # noqa: S608
        {"ids": list(source_record_ids)},
    )
    conn.execute(text(f"ALTER TABLE {_SNAPSHOT} ADD PRIMARY KEY (id)"))


def delete_processed_marks(conn: Connection) -> None:
    """Supprime de la file les marquages relevés par `snapshot_queued_source_records`, puis le relevé."""
    delete_processed(conn, Queue.SOURCE_RECORD_KEYS, _SNAPSHOT)
    conn.execute(text(f"DROP TABLE {_SNAPSHOT}"))


def fetch_reconciliation_universe(conn: Connection) -> list[ReconcileRow]:
    """Le voisinage 1-hop : les enregistrements sources relevés dans la file (orphelins compris) **et** les enregistrements sources qui partagent une clé de confirmation (DOI / NNT / hal_id / PMID, ou le composite thèse `title_normalized`+`publication_year`) ou une fusion manuelle avec l'un d'eux — matérialisés ou orphelins. Univers sur lequel tourne `connected_components`."""
    rows = conn.execute(_UNIVERSE_SQL).all()
    return [
        ReconcileRow(
            r.id,
            r.doi,
            parse_identifiers(r.identifiers),
            r.publication_id,
            r.doc_type,
            r.title_normalized,
            r.publication_year,
            r.is_matchable,
            r.publication_doi,
            r.in_perimeter,
            r.manual_merge_ids,
        )
        for r in rows
    ]


def fetch_publication_ids_by_doi(conn: Connection) -> dict[str, int]:
    """Map `lower(doi) → id` des publications existantes qui ont un DOI.

    Permet à `plan_reconciliation` d'ancrer un groupe sur la publication qui a déjà son DOI même quand **aucun** enregistrement source du voisinage n'y est rattaché — publication devenue orpheline après un TRUNCATE + réimport des sources, ou dérive du `publications.doi` vis-à-vis de ses sources. Sans cela, le groupe créerait une publication qui heurterait la contrainte unique sur le DOI."""
    # Clé sur `lower(doi)` : l'index unique `publications_doi_lower_key` garantit l'unicité, et le DOI de partition (`effective_doi`, via `clean_doi`) est déjà en minuscule.
    rows = conn.execute(
        text("SELECT id, lower(doi) AS doi FROM publications WHERE doi IS NOT NULL")
    ).all()
    return {row.doi: row.id for row in rows}


def fetch_publication_sizes(conn: Connection, publication_ids: list[int]) -> dict[int, int]:
    """Nombre de `source_records` rattachées à chacune des publications `publication_ids`."""
    rows = conn.execute(
        text("""
            SELECT publication_id, count(*) AS n FROM source_records
            WHERE publication_id = ANY(:ids) GROUP BY publication_id
        """),
        {"ids": publication_ids},
    ).all()
    return {row.publication_id: row.n for row in rows}


def repoint_source_records(
    conn: Connection, source_record_ids: list[int], publication_id: int
) -> None:
    """Rattache un ensemble de `source_records` à `publication_id` (assignation d'un groupe)."""
    if not source_record_ids:
        return
    stmt = text("UPDATE source_records SET publication_id = :pid WHERE id = ANY(:ids)").bindparams(
        bindparam("ids")
    )
    conn.execute(stmt, {"pid": publication_id, "ids": source_record_ids})


def detach_source_records(conn: Connection, source_record_ids: list[int]) -> None:
    """Détache un ensemble de `source_records` de leur publication : elles deviennent orphelines."""
    if not source_record_ids:
        return
    stmt = text("UPDATE source_records SET publication_id = NULL WHERE id = ANY(:ids)").bindparams(
        bindparam("ids")
    )
    conn.execute(stmt, {"ids": source_record_ids})


def mark_publications_for_grouping(conn: Connection, publication_ids: list[int]) -> int:
    """Marque ces publications pour le groupement des auteurs. Retourne le nombre de publications marquées."""
    if not publication_ids:
        return 0
    return enqueue(
        conn,
        Queue.PUBLICATION_CONTRIBUTIONS,
        "SELECT unnest(CAST(:ids AS integer[]))",
        {"ids": publication_ids},
    )


# ─── Réconciliation ──────────────────────────────────────────────


def _member(row: ReconcileRow) -> ReconcileMember:
    keys = project_confirmation_keys(
        row.doi, row.identifiers, row.doc_type, row.title_normalized, row.publication_year
    )
    return ReconcileMember(
        source_record_id=row.id,
        publication_id=row.publication_id,
        publication_doi=row.publication_doi,
        effective_doi=keys.doi,
        tokens=keys.tokens() | manual_merge_tokens(row.manual_merge_ids),
        in_perimeter=row.in_perimeter,
        title_normalized=row.title_normalized,
        publication_year=row.publication_year,
        doc_type=row.doc_type,
        matchable=row.is_matchable,
    )


def _create_new_publication(
    conn: Connection, group: WorkGroup, rows_by_source_record: dict[int, ReconcileRow]
) -> int:
    """Crée la publication d'un groupe sans ancre existante (split, ou création depuis orphelins), semée depuis son plus petit enregistrement source qui a une année. Les métadonnées définitives sont posées juste après par `lifecycle.refresh`.

    Un groupe `target=None` est soit une partition d'orphelins ayant passé le gate `has_minimal_publication_metadata` (≥1 membre titre + année), soit une partition split perdante (membres matérialisés, qui avaient déjà une année) — dans les deux cas ≥1 membre a une année."""
    seed = min(
        (
            rows_by_source_record[source_record]
            for source_record in group.source_record_ids
            if rows_by_source_record[source_record].publication_year
        ),
        key=lambda r: r.id,
    )
    assert seed.publication_year is not None
    return lifecycle.create(
        conn,
        title_normalized=seed.title_normalized or "",
        doc_type=seed.doc_type,
        publication_year=seed.publication_year,
        doi=seed.doi,
    )


class ReconcileStats(NamedTuple):
    """Bilan d'une passe de réconciliation.

    `processed` = enregistrements sources en file traités ; `publications` = publications résultantes (auxquelles des enregistrements sources sont rattachés) ; `created` = parmi elles, publications créées (orphelins matérialisés **et** spin-offs de scission) ; `existing` = publications existantes conservées ; `merges` = publications redondantes absorbées dans une autre et supprimées ; `splits` = publications créées par une scission (un DOI distinct détaché d'une publication existante) ; `detached` = `source_records` rendues orphelines, faute de pouvoir fonder une publication.
    """

    processed: int = 0
    publications: int = 0
    created: int = 0
    existing: int = 0
    merges: int = 0
    splits: int = 0
    detached: int = 0


class AppliedReconciliation(NamedTuple):
    """Effet d'une réconciliation appliquée.

    `survivors` = publications auxquelles des enregistrements sources sont rattachés ; `changed` = publications conservées qui gagnent ou perdent un enregistrement source ; `created` = publications créées, dont `splits` par une scission.
    """

    survivors: frozenset[int]
    changed: frozenset[int]
    created: int
    splits: int


def _plan(conn: Connection) -> tuple[ReconcilePlan, dict[int, ReconcileRow]]:
    """Planifie la réconciliation du voisinage des enregistrements sources relevés. Rend le plan et les lignes du voisinage par enregistrement source."""
    rows = fetch_reconciliation_universe(conn)
    publication_sizes = fetch_publication_sizes(
        conn, sorted({row.publication_id for row in rows if row.publication_id is not None})
    )
    plan = plan_reconciliation(
        (_member(row) for row in rows),
        existing_publication_by_doi=fetch_publication_ids_by_doi(conn),
        publication_sizes=publication_sizes,
    )
    return plan, {row.id: row for row in rows}


def _apply(
    conn: Connection, plan: ReconcilePlan, rows_by_source_record: dict[int, ReconcileRow]
) -> AppliedReconciliation:
    """Applique le plan : rattachements, détachements, dissolutions. Les publications conservées restent à rafraîchir."""
    survivors: set[int] = set()
    # Publications qui gagnent ou perdent un enregistrement source.
    membership_changed: set[int] = set()
    created = 0
    splits = 0

    # 1. Groupes : rattacher chaque enregistrement source à son ancre, ou à une publication créée — orphelins in-périmètre, ou partition perdante d'un split = scission d'une publication existante.
    for group in plan.groups:
        target = group.target_publication_id
        if target is None:
            from_existing = any(
                rows_by_source_record[source_record].publication_id is not None
                for source_record in group.source_record_ids
            )
            target = _create_new_publication(conn, group, rows_by_source_record)
            created += 1
            if from_existing:
                splits += 1
        repoint_source_records(conn, list(group.source_record_ids), target)
        survivors.add(target)
        for source_record in group.source_record_ids:
            if (previous := rows_by_source_record[source_record].publication_id) != target:
                membership_changed.update(p for p in (previous, target) if p is not None)

    # 2. Détachements : les enregistrements sources écartés et les membres d'une partition qui ne
    # peut fonder aucune publication deviennent orphelins. Leur ancienne publication est
    # recalculée, et supprimée si elle reste sans source. Une publication dissoute est laissée à
    # l'étape 3, qui redirige ses paiements APC avant de la supprimer.
    dissolved_ids = {dissolved.publication_id for dissolved in plan.dissolved}
    if plan.detached:
        detach_source_records(conn, list(plan.detached))
        membership_changed.update(
            p
            for source_record in plan.detached
            if (p := rows_by_source_record[source_record].publication_id) is not None
        )
        for publication_id in sorted(
            {
                p
                for source_record in plan.detached
                if (p := rows_by_source_record[source_record].publication_id) is not None
            }
            - survivors
            - dissolved_ids
        ):
            with savepoint(conn):
                lifecycle.refresh(conn, publication_id)

    # 3. Dissolutions, avant les survivants : la suppression libère le DOI qu'un survivant
    # reprend, que la contrainte unique refuserait sinon.
    for dissolved in plan.dissolved:
        lifecycle.dissolve(conn, dissolved.publication_id, dissolved.successor_publication_id)

    return AppliedReconciliation(
        survivors=frozenset(survivors),
        changed=frozenset(membership_changed - dissolved_ids),
        created=created,
        splits=splits,
    )


def _refresh(conn: Connection, publication_id: int) -> None:
    """Recalcule les métadonnées consolidées d'une publication depuis ses sources."""
    with savepoint(conn):
        lifecycle.refresh(conn, publication_id)


def _snapshot_publications(conn: Connection) -> set[int]:
    """Publications des enregistrements sources relevés."""
    return set(
        conn.execute(
            text(
                f"SELECT DISTINCT sr.publication_id FROM {_SNAPSHOT} m"  # noqa: S608
                " JOIN source_records sr ON sr.id = m.id WHERE sr.publication_id IS NOT NULL"
            )
        ).scalars()
    )


def _publications_to_refresh(
    conn: Connection, plan: ReconcilePlan, applied: AppliedReconciliation, before: set[int]
) -> list[int]:
    """Publications à recalculer : celles des enregistrements sources relevés, avant (`before`) comme après la réconciliation, et les cibles des groupes. Les publications dissoutes en sortent."""
    dissolved = {d.publication_id for d in plan.dissolved}
    return sorted((before | _snapshot_publications(conn) | applied.survivors) - dissolved)


def reconcile(conn: Connection, logger: logging.Logger, *, rebuild: bool = False) -> ReconcileStats:
    """Planifie et applique la réconciliation du voisinage des enregistrements sources en file, puis supprime les marquages traités. Rend un bilan à zéro si la file est vide. Le commit est à la charge de l'appelant.

    `rebuild` marque d'abord toutes les `source_records` : la réconciliation reprend alors le stock entier.
    """
    if rebuild:
        mark_for_reconciliation(conn)
    mark_publication_siblings(conn)
    dirty_ids = snapshot_queued_source_records(conn)
    if not dirty_ids:
        delete_processed_marks(conn)
        step(logger, "Aucun document nouveau ou mis à jour")
        nothing_to_do(logger)
        return ReconcileStats()
    step(
        logger,
        "%s %s (%s)",
        quantity(len(dirty_ids), "document"),
        inflect(len(dirty_ids), "examiné"),
        "reconstruction complète" if rebuild else "nouveaux ou mis à jour",
    )
    with waiting(BRANCH, logger) as line:
        plan, rows_by_source_record = _plan(conn)
        # Le plan sépare déjà les publications à créer de celles qu'un groupe rejoint.
        to_create = sum(1 for g in plan.groups if g.target_publication_id is None)
        existing = len(plan.groups) - to_create
        line.conclude(
            f"{BRANCH}résolus en {quantity(len(plan.groups), 'publication')} "
            f"({existing} déjà {inflect(existing, 'existante')}, {quantity(to_create, 'nouvelle')} ; "
            f"{quantity(len(plan.dissolved), 'doublon')} à fusionner)"
        )

    before = _snapshot_publications(conn)
    t0 = time.perf_counter()
    with waiting(f"{LAST_BRANCH}application", logger) as line:
        applied = _apply(conn, plan, rows_by_source_record)
        line.conclude(f"{LAST_BRANCH}Terminé en {time.perf_counter() - t0:.1f}s")

    # 4. Recalcul des métadonnées consolidées depuis les sources.
    to_refresh = _publications_to_refresh(conn, plan, applied, before)
    step(logger, "Recalcul des métadonnées consolidées")
    with track_progress(len(to_refresh), LAST_BRANCH.rstrip(), logger) as progress:
        for publication_id in to_refresh:
            progress.advance()
            _refresh(conn, publication_id)

    # 5. Les publications qui gagnent ou perdent un enregistrement source regroupent leurs contributions sources.
    mark_publications_for_grouping(conn, sorted(applied.changed))
    delete_processed_marks(conn)
    return ReconcileStats(
        processed=len(dirty_ids),
        publications=len(applied.survivors),
        created=applied.created,
        existing=len(applied.survivors) - applied.created,
        merges=len(plan.dissolved),
        splits=applied.splits,
        detached=len(plan.detached),
    )


def reconcile_source_records(
    conn: Connection, source_record_ids: Sequence[int]
) -> AppliedReconciliation:
    """Réconcilie le voisinage des enregistrements sources `source_record_ids`, hors de la file, et recalcule les métadonnées consolidées des publications touchées (`_publications_to_refresh`). Le commit est à la charge de l'appelant.

    Les publications qui gagnent ou perdent un enregistrement source sont marquées pour le groupement des auteurs.
    """
    snapshot_source_records(conn, source_record_ids)
    plan, rows_by_source_record = _plan(conn)
    before = _snapshot_publications(conn)
    applied = _apply(conn, plan, rows_by_source_record)
    for publication_id in _publications_to_refresh(conn, plan, applied, before):
        _refresh(conn, publication_id)
    mark_publications_for_grouping(conn, sorted(applied.changed))
    conn.execute(text(f"DROP TABLE {_SNAPSHOT}"))
    return applied
