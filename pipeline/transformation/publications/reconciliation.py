"""Réconciliation des enregistrements sources avec les publications (tâche `publications.reconcile`).

Les enregistrements sources de la file `source_record_keys_queue` et leurs voisins directs reçoivent un plan de `domain.publications.reconciliation.plan_reconciliation`, appliqué par ce module :

- les enregistrements sources de chaque groupe rejoignent son ancre, ou une publication créée ;
- une publication dissoute redirige ses paiements APC et son identifiant vers son successeur, puis est supprimée (`lifecycle.dissolve`) ;
- `lifecycle.refresh` recalcule chaque publication touchée, avant comme après la réconciliation, et supprime celles restées sans enregistrement source.

Les publications qui gagnent ou perdent un enregistrement source sont marquées pour l'alignement de leurs auteurs (`author_grouping`), qui recompose leurs contributions.

Le voisinage direct suffit : l'invariant du marquage garantit que toute arête ajoutée a une extrémité marquée. La passe commence par marquer les enregistrements sources rattachés à la même publication qu'un enregistrement source marqué. Le voisinage couvre ainsi les arêtes retirées comme les ajoutées.

`reconcile_source_records` applique la même passe à une liste d'enregistrements sources, hors de la file, après une fusion manuelle dans l'administration.
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
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.keys import (
    CONFIRMATION_ID_TYPES,
    DISCRIMINANT_TITLE_MIN_LENGTH,
    project_confirmation_keys,
)
from infrastructure.db.doi_targets import doi_or_target_sql, fetch_doi_targets
from infrastructure.db.queues import Queue, delete_processed, enqueue, snapshot
from infrastructure.db.savepoint import savepoint
from infrastructure.db.scalars import scalar_int
from infrastructure.db.source_record_identifiers import (
    first_of_its_type_sql,
    identifiers_json_sql,
    parse_identifiers,
)
from infrastructure.sql_fragments import in_clause
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


class ReconcileRow(NamedTuple):
    """Enregistrement source du voisinage : clés et publication courante."""

    id: int
    identifiers: tuple[SourceIdentifier, ...]
    publication_id: int | None
    """`None` si l'enregistrement source est orphelin."""
    doc_type: str | None
    """Avec `title_normalized` et `publication_year`, alimente le token métadonnée de `project_confirmation_keys`."""
    title_normalized: str | None
    publication_year: int | None
    is_matchable: bool
    """Vrai si l'enregistrement source entre dans la réconciliation."""
    publication_doi: str | None
    """DOI de la publication courante, pour choisir l'ancre ; `None` si l'enregistrement source est orphelin."""
    in_perimeter: bool
    """Vrai si l'enregistrement source a au moins une contribution source dans le périmètre : condition de création d'une publication."""
    manual_merge_ids: list[int]
    """Fusions manuelles désignant l'enregistrement source."""


# Relevé de la file `source_record_keys_queue`.
_SNAPSHOT = "source_record_keys_marks"

# Colonnes du voisinage direct : enregistrements sources relevés dans la file (orphelins compris) et enregistrements sources partageant une clé de confirmation avec eux.
# `publication_doi` sert au choix de l'ancre. `in_perimeter` conditionne la création d'une publication pour une partition d'orphelins.
_COLS = (
    "{a}.id, " + identifiers_json_sql("{a}.id") + " AS identifiers, {a}.publication_id, "
    "{a}.doc_type, {a}.title_normalized, {a}.publication_year, {a}.is_matchable, "
    "p.doi AS publication_doi, "
    "EXISTS (SELECT 1 FROM source_contributions sc "
    "WHERE sc.source_record_id = {a}.id AND sc.in_perimeter) AS in_perimeter, "
    "ARRAY(SELECT mm.manual_merge_id FROM manual_merge_source_records mm "
    "WHERE mm.source = {a}.source AND mm.source_id = {a}.source_id "
    "ORDER BY mm.manual_merge_id) AS manual_merge_ids"
)

# L'identifiant aliasé `{a}` de `source_record_identifiers` est la clé de confirmation de son type (`confirmation_identifiers`).
_CONFIRMATION_KEY_SQL = (
    "{a}.id_type::text IN "
    + in_clause(tuple(map(str, CONFIRMATION_ID_TYPES)))
    + " AND "
    + first_of_its_type_sql("{a}")
)

# L'identifiant aliasé `{a}` de `source_record_identifiers` est une clé DOI : un DOI actif de rôle autre que `related` (`doi_keys`).
_DOI_KEY_SQL = (
    f"{{a}}.id_type = '{SourceIdentifierType.DOI.value}' AND {{a}}.removed_by IS NULL"
    f" AND {{a}}.role <> '{SourceIdentifierRole.RELATED.value}'"
)

_UNIVERSE_SQL = text(f"""
    WITH dirty AS (
        SELECT {_COLS.format(a="sr")}
        FROM {_SNAPSHOT} m
        JOIN source_records sr ON sr.id = m.id
        LEFT JOIN publications p ON p.id = sr.publication_id
    )
    SELECT id, identifiers, publication_id, doc_type, title_normalized, publication_year,
           is_matchable, publication_doi, in_perimeter, manual_merge_ids
    FROM dirty
    UNION
    -- DOI : une clé DOI de l'autre enregistrement source égale à une clé DOI de `d`, cible
    -- appliquée (`doi_targets`), par l'index `idx_source_record_identifiers_value`.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_record_identifiers di ON di.source_record_id = d.id AND {_DOI_KEY_SQL.format(a="di")}
    JOIN source_record_identifiers oi
      ON oi.id_type = di.id_type AND oi.id_value = {doi_or_target_sql("di.id_value")}
         AND {_DOI_KEY_SQL.format(a="oi")}
    JOIN source_records o ON o.id = oi.source_record_id
    LEFT JOIN publications p ON p.id = o.publication_id
    UNION
    -- DOI d'une forme secondaire dont la cible est une clé DOI de `d`.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_record_identifiers di ON di.source_record_id = d.id AND {_DOI_KEY_SQL.format(a="di")}
    JOIN doi_targets t ON t.target_doi = {doi_or_target_sql("di.id_value")}
    JOIN source_record_identifiers oi
      ON oi.id_type = di.id_type AND oi.id_value = t.doi AND {_DOI_KEY_SQL.format(a="oi")}
    JOIN source_records o ON o.id = oi.source_record_id
    LEFT JOIN publications p ON p.id = o.publication_id
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


# Enregistrements sources hors file rattachés à la même publication qu'un enregistrement source en file (`mark_publication_siblings`).
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
    """Marque pour la réconciliation tous les enregistrements sources, ou le sous-ensemble `where`. Renvoie le nombre d'enregistrements sources marqués, ou à marquer avec `dry_run`.

    Sert après un changement de règle des clés de confirmation (token, seuil de garde, projection) : le stock déjà réconcilié diverge alors de la règle. Les enregistrements sources marqués sont réconciliés de nouveau au prochain run de la phase `publications`.

    Args:
        where: fragment SQL de confiance (CLI de maintenance, `run_pipeline`), jamais une entrée externe.
        dry_run: compte sans écrire.
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
    """Marque pour la réconciliation les enregistrements sources rattachés à la même publication qu'un enregistrement source en file. Renvoie le nombre de lignes marquées.

    Le voisinage direct est calculé sur les clés courantes. Un enregistrement source rattaché par une clé de confirmation disparue est donc absent du voisinage direct. Exemple : un DOI de préversion remplacé chez la source par celui de la version publiée. Marqué, cet enregistrement source est réexaminé et rejoint la publication de ses voisins, sans publication en doublon.
    """
    return enqueue(conn, Queue.SOURCE_RECORD_KEYS, _SIBLINGS_SQL, {})


def snapshot_queued_source_records(conn: Connection) -> list[int]:
    """Relève la file des enregistrements sources à réconcilier, orphelins compris : la réconciliation fait aussi l'assignation. Renvoie les identifiants des enregistrements sources existants. `delete_processed_marks` retire de la file tous les marquages relevés."""
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
    """Renvoie le voisinage direct, univers de `connected_components`.

    Le voisinage réunit les enregistrements sources relevés dans la file (orphelins compris) et les enregistrements sources, rattachés ou orphelins, partageant avec eux une clé de confirmation ou une fusion manuelle. Les clés de confirmation sont le DOI, les identifiants de `CONFIRMATION_ID_TYPES` et le token métadonnée (`doc_type`, `title_normalized`, `publication_year`).
    """
    rows = conn.execute(_UNIVERSE_SQL).all()
    return [
        ReconcileRow(
            r.id,
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
    """Renvoie `lower(doi) → id` des publications à DOI.

    `plan_reconciliation` peut ainsi ancrer un groupe sur la publication ayant déjà son DOI, même sans enregistrement source du voisinage rattaché à elle. Cas : publication orpheline après un TRUNCATE et un réimport des sources, ou `publications.doi` différent de ses enregistrements sources. Sinon, le groupe créerait une publication en conflit avec la contrainte unique sur le DOI.
    """
    # Clé sur `lower(doi)` : l'index unique `publications_doi_lower_key` garantit l'unicité, et l'ancre DOI d'une partition, forme normalisée d'un identifiant, est déjà en minuscule.
    rows = conn.execute(
        text("SELECT id, lower(doi) AS doi FROM publications WHERE doi IS NOT NULL")
    ).all()
    return {row.doi: row.id for row in rows}


def fetch_publication_sizes(conn: Connection, publication_ids: list[int]) -> dict[int, int]:
    """Compte les enregistrements sources rattachés à chacune des publications `publication_ids`."""
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
    """Rattache des enregistrements sources à `publication_id` (assignation d'un groupe)."""
    if not source_record_ids:
        return
    stmt = text("UPDATE source_records SET publication_id = :pid WHERE id = ANY(:ids)").bindparams(
        bindparam("ids")
    )
    conn.execute(stmt, {"pid": publication_id, "ids": source_record_ids})


def detach_source_records(conn: Connection, source_record_ids: list[int]) -> None:
    """Détache des enregistrements sources de leur publication : ils deviennent orphelins."""
    if not source_record_ids:
        return
    stmt = text("UPDATE source_records SET publication_id = NULL WHERE id = ANY(:ids)").bindparams(
        bindparam("ids")
    )
    conn.execute(stmt, {"ids": source_record_ids})


def mark_publications_for_grouping(conn: Connection, publication_ids: list[int]) -> int:
    """Marque ces publications pour l'alignement des auteurs. Renvoie le nombre de publications marquées."""
    if not publication_ids:
        return 0
    return enqueue(
        conn,
        Queue.PUBLICATION_CONTRIBUTIONS,
        "SELECT unnest(CAST(:ids AS integer[]))",
        {"ids": publication_ids},
    )


def _member(row: ReconcileRow, doi_targets: dict[str, str]) -> ReconcileMember:
    keys = project_confirmation_keys(
        row.identifiers, row.doc_type, row.title_normalized, row.publication_year, doi_targets
    )
    return ReconcileMember(
        source_record_id=row.id,
        publication_id=row.publication_id,
        publication_doi=row.publication_doi,
        doi_keys=keys.doi,
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
    """Crée la publication d'un groupe sans ancre existante (scission, ou création depuis des orphelins), d'après son enregistrement source à année de plus petit id. `lifecycle.refresh` pose ensuite les métadonnées définitives.

    Un groupe sans cible a toujours un membre à année. C'est soit une partition d'orphelins admise par `has_minimal_publication_metadata` (un membre à titre et année), soit la partition perdante d'une scission (membres déjà rattachés, donc à année).
    """
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
        doi=group.doi,
    )


class ReconcileStats(NamedTuple):
    """Bilan d'une passe de réconciliation."""

    processed: int = 0
    """Enregistrements sources en file traités."""
    publications: int = 0
    """Publications à enregistrements sources rattachés, après la passe."""
    created: int = 0
    """Publications créées parmi `publications`, depuis des orphelins ou par scission."""
    existing: int = 0
    """Publications existantes conservées."""
    merges: int = 0
    """Publications redondantes absorbées dans une autre, puis supprimées."""
    splits: int = 0
    """Publications créées par une scission : un DOI distinct détaché d'une publication existante."""
    detached: int = 0
    """Enregistrements sources rendus orphelins, faute de pouvoir fonder une publication."""


class AppliedReconciliation(NamedTuple):
    """Effet d'une réconciliation appliquée."""

    survivors: frozenset[int]
    """Publications à enregistrements sources rattachés."""
    changed: frozenset[int]
    """Publications conservées qui gagnent ou perdent un enregistrement source."""
    created: int
    splits: int
    """Publications créées par une scission, parmi `created`."""


def _plan(conn: Connection) -> tuple[ReconcilePlan, dict[int, ReconcileRow]]:
    """Planifie la réconciliation du voisinage des enregistrements sources relevés. Renvoie le plan et les lignes du voisinage par enregistrement source."""
    rows = fetch_reconciliation_universe(conn)
    publication_sizes = fetch_publication_sizes(
        conn, sorted({row.publication_id for row in rows if row.publication_id is not None})
    )
    doi_targets = fetch_doi_targets(conn, (i for row in rows for i in row.identifiers))
    plan = plan_reconciliation(
        (_member(row, doi_targets) for row in rows),
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

    # Groupes : chaque enregistrement source rejoint son ancre, ou une publication créée.
    # Une publication est créée pour des orphelins du périmètre, ou pour la partition perdante d'une scission.
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

    # Détachements : les enregistrements sources écartés et les membres d'une partition incapable de fonder une publication deviennent orphelins.
    # Leur ancienne publication est recalculée, et supprimée si elle reste sans enregistrement source.
    # Une publication dissoute est laissée à l'étape des dissolutions, qui redirige ses paiements APC avant de la supprimer.
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

    # Dissolutions, avant le recalcul des survivants : la suppression libère le DOI repris par un survivant, refusé sinon par la contrainte unique.
    for dissolved in plan.dissolved:
        lifecycle.dissolve(conn, dissolved.publication_id, dissolved.successor_publication_id)

    return AppliedReconciliation(
        survivors=frozenset(survivors),
        changed=frozenset(membership_changed - dissolved_ids),
        created=created,
        splits=splits,
    )


def _refresh(conn: Connection, publication_id: int) -> None:
    """Recalcule les métadonnées consolidées d'une publication depuis ses enregistrements sources."""
    with savepoint(conn):
        lifecycle.refresh(conn, publication_id)


def _snapshot_publications(conn: Connection) -> set[int]:
    """Renvoie les publications des enregistrements sources relevés."""
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
    """Renvoie les publications à recalculer : celles des enregistrements sources relevés, avant (`before`) comme après la réconciliation, et les cibles des groupes. Les publications dissoutes sont exclues."""
    dissolved = {d.publication_id for d in plan.dissolved}
    return sorted((before | _snapshot_publications(conn) | applied.survivors) - dissolved)


def reconcile(conn: Connection, logger: logging.Logger, *, rebuild: bool = False) -> ReconcileStats:
    """Planifie et applique la réconciliation du voisinage des enregistrements sources en file, puis supprime les marquages traités. Renvoie un bilan à zéro si la file est vide. Le commit est à la charge de l'appelant.

    Args:
        rebuild: marque d'abord tous les enregistrements sources, pour reprendre le stock entier.
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
        # Le plan sépare déjà les publications à créer des publications rejointes par un groupe.
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

    # Recalcul des métadonnées consolidées depuis les enregistrements sources.
    to_refresh = _publications_to_refresh(conn, plan, applied, before)
    step(logger, "Recalcul des métadonnées consolidées")
    with track_progress(len(to_refresh), LAST_BRANCH.rstrip(), logger) as progress:
        for publication_id in to_refresh:
            progress.advance()
            _refresh(conn, publication_id)

    # Les publications qui gagnent ou perdent un enregistrement source sont marquées pour l'alignement des auteurs.
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

    Les publications qui gagnent ou perdent un enregistrement source sont marquées pour l'alignement des auteurs.
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
