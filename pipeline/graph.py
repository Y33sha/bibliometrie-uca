"""Tâches, étapes et phases du pipeline, et graphe de dépendances des tâches d'après leurs lectures et leurs écritures.

Le module de chaque phase déclare ses étapes et ses tâches. `pipeline.phases` liste les phases dans l'ordre d'exécution. L'ordre des tâches est celui d'un parcours en profondeur des phases et de leurs étapes.

Une donnée se désigne par sa table (`"serials"`) ou par une colonne (`"serials.serial_type"`). `"serials.id"` désigne l'existence des lignes, créées et supprimées par les écrivains. Une table et l'une de ses colonnes se recouvrent.

Une tâche dépend des tâches placées avant elle et écrivant une donnée lue par elle. Une lecture déclarée `previous_run` lit aussi les écritures du run précédent, faites par une tâche placée après elle ou par elle-même. Les tests vérifient que l'ordre d'exécution ne fait lire à aucune tâche une donnée écrite après elle, sauf lecture du run précédent déclarée.

La maintenance d'une tâche (`VACUUM`, `ANALYZE`) suit ses écritures et ne crée aucune dépendance. Des tâches consécutives du même `parallel_group` s'exécutent en parallèle, une file par source (`network`) : les tâches d'une même source s'enchaînent dans l'ordre, les sources s'exécutent en même temps. Une tâche peut dépendre d'une tâche de sa source placée avant elle, jamais d'une tâche d'une autre source du groupe.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pipeline.http.circuit_breaker import DEFAULT_THRESHOLD

if TYPE_CHECKING:
    import logging

    from sqlalchemy import Connection

    from pipeline.runtime.context import PhaseContext
    from pipeline.runtime.observability.metrics import PhaseMetrics


@dataclass(frozen=True, slots=True)
class Task:
    """Tâche du pipeline, avec ses lectures et ses écritures."""

    name: str
    """Nom de la tâche, unique dans sa phase : `attach_serials`."""
    _: KW_ONLY
    run: TaskRun
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    previous_run: tuple[str, ...] = ()
    """Lectures de données écrites au run précédent, par une tâche placée après elle ou par la tâche elle-même."""
    network: str | None = None
    """API interrogée, si la tâche sort sur le réseau."""
    maintenance: tuple[str, ...] = ()
    """Maintenance physique des tables, dans l'ordre : `VACUUM staging`, `ANALYZE source_contributions`."""
    parallel_group: str | None = None
    """Groupe de tâches consécutives exécutées en parallèle, une file par source, nommé dans sa phase."""
    section: str | None = None
    """Section de la tâche au journal, hors d'une étape de premier niveau qui en a une. `None` : la tâche écrit sous la section courante."""
    label: str | None = None
    """Libellé de la ligne de bilan. `None` : la tâche écrit elle-même ses lignes."""
    threshold: int = DEFAULT_THRESHOLD
    """Échecs consécutifs avant la coupure du circuit-breaker de la source."""
    when: Callable[[PhaseContext], bool] | None = None
    """Condition d'exécution, évaluée avant l'accès à la source. Une tâche écartée n'écrit rien."""
    silent_when_empty: bool = False
    """La tâche n'écrit rien sans élément traité : `total` nul, sans signal."""


type TaskRun = Callable[[PhaseContext], PhaseMetrics]
"""Exécute une tâche dans le contexte de sa phase."""


def in_transaction(run: Callable[[Connection, logging.Logger], PhaseMetrics]) -> TaskRun:
    """Renvoie l'exécution de `run` dans une transaction de la phase."""

    def execute(ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            return run(conn, ctx.logger)

    return execute


def overlaps(a: str, b: str) -> bool:
    """Indique si deux données se recouvrent : même table, et même colonne si les deux désignent une colonne."""
    table_a, _, column_a = a.partition(".")
    table_b, _, column_b = b.partition(".")
    return table_a == table_b and (not column_a or not column_b or column_a == column_b)


def _overlaps_any(item: str, items: Iterable[str]) -> bool:
    return any(overlaps(item, other) for other in items)


def _affected_by(read: str, write: str) -> bool:
    """Indique si l'écriture `write` change la lecture `read`. Créer ou supprimer des lignes (`id`) change toutes les lectures de la table."""
    return overlaps(read, write) or (
        write.partition(".")[2] == "id" and read.partition(".")[0] == write.partition(".")[0]
    )


def _writes_read(reader: Task, writer: Task) -> list[str]:
    return [r for r in reader.reads if any(_affected_by(r, w) for w in writer.writes)]


def reads_from(children: Iterable[Step | Task], writer: Task) -> bool:
    """Indique si une tâche de `children` lit une donnée écrite par `writer`."""
    return any(_writes_read(task, writer) for task in leaves(children))


def concurrent(a: Task, b: Task) -> bool:
    """Indique si deux tâches s'exécutent en même temps : même groupe parallèle, sources différentes."""
    return (
        a.parallel_group is not None
        and a.parallel_group == b.parallel_group
        and a.network != b.network
    )


def dependencies(tasks: Sequence[Task]) -> dict[str, set[str]]:
    """Renvoie, pour chaque tâche, les tâches placées avant elle, exécutées avant elle (`concurrent`), et écrivant une donnée lue par elle."""
    return {
        reader.name: {
            writer.name
            for writer in tasks[:i]
            if not concurrent(reader, writer) and _writes_read(reader, writer)
        }
        for i, reader in enumerate(tasks)
    }


def order_violations(tasks: Sequence[Task]) -> list[tuple[str, str, str]]:
    """Renvoie les triplets (lecteur, donnée, écrivain) où l'écrivain, placé après le lecteur, écrit une donnée lue par le lecteur sans déclaration `previous_run`."""
    return sorted(
        (reader.name, item, writer.name)
        for i, reader in enumerate(tasks)
        for writer in tasks[i + 1 :]
        for item in _writes_read(reader, writer)
        if not _overlaps_any(item, reader.previous_run)
    )


@dataclass(frozen=True)
class Step:
    """Étape d'une phase : tâches et étapes exécutées dans l'ordre."""

    name: str
    summary: str
    """Entrées → sorties de l'étape."""
    children: tuple[Step | Task, ...]
    section: str | None = None
    """Section des tâches d'une étape de premier niveau, au journal. `None` : chaque tâche écrit sous sa propre `section`."""

    @property
    def tasks(self) -> tuple[Task, ...]:
        return leaves(self.children)


def leaves(children: Iterable[Step | Task]) -> tuple[Task, ...]:
    """Renvoie les tâches de `children`, dans l'ordre d'exécution."""
    return tuple(
        task
        for child in children
        for task in (child.tasks if isinstance(child, Step) else (child,))
    )


def interface(children: Iterable[Step | Task]) -> tuple[frozenset[str], frozenset[str]]:
    """Renvoie les données lues par `children` hors de ses propres écritures précédentes, et les données écrites par `children`."""
    reads: set[str] = set()
    writes: list[str] = []
    for task in leaves(children):
        reads.update(r for r in task.reads if not any(_affected_by(r, w) for w in writes))
        writes.extend(task.writes)
    return frozenset(reads), frozenset(writes)


class Block(StrEnum):
    """Bloc du premier niveau de l'arborescence du pipeline. Il regroupe les phases à l'affichage, sans effet sur l'exécution."""

    HARVESTING = "Moissonnage"
    SOURCE_RECORDS = "Enregistrements sources"
    ENTITIES = "Entités"
    DERIVED_DATA = "Données dérivées"
    ENRICHMENTS = "Enrichissements"
    """Phases hors résolution d'entités : `--no-extras` les omet."""


@dataclass(frozen=True)
class Phase:
    """Phase du pipeline : étapes et tâches consécutives, avec leur libellé et leurs attributs."""

    name: str
    label: str
    """Libellé lisible sans connaître le schéma."""
    children: tuple[Step | Task, ...]
    block: Block
    when: Callable[[PhaseContext], bool] | None = None
    """Condition d'exécution, évaluée avant la précondition. Une phase écartée le signale au journal et renvoie des métriques vides."""
    check: Callable[[PhaseContext], None] | None = None
    """Précondition, vérifiée avant les tâches : lève une exception si elle n'est pas remplie."""
    assemble: Callable[[Mapping[str, PhaseMetrics]], PhaseMetrics] | None = None
    """Métriques de la phase, d'après celles de ses tâches exécutées, par nom de tâche. `None` : leur somme."""

    @property
    def tasks(self) -> tuple[Task, ...]:
        return leaves(self.children)

    @property
    def extra(self) -> bool:
        """Enrichissement : `--no-extras` omet la phase."""
        return self.block is Block.ENRICHMENTS
