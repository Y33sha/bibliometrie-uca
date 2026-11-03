"""Graphe de dépendances du pipeline : les tâches, leurs lectures et leurs écritures, dans l'ordre d'exécution. Chaque tâche appartient à une phase. `pipeline.phases` donne l'ordre des phases.

Une donnée se désigne par sa table (`"serials"`) ou par une colonne (`"serials.serial_type"`). `"serials.id"` désigne l'existence des lignes, créées et supprimées par les écrivains. Une table et l'une de ses colonnes se recouvrent.

Une tâche dépend des tâches placées avant elle et écrivant une donnée lue par elle. Une lecture déclarée `previous_run` lit aussi les écritures du run précédent, faites par une tâche placée après elle ou par elle-même. Les tests vérifient que l'ordre d'exécution ne fait lire à aucune tâche une donnée écrite après elle, sauf lecture du run précédent déclarée.

La maintenance d'une tâche (`VACUUM`, `ANALYZE`) suit ses écritures et ne crée aucune dépendance. Des tâches consécutives du même `parallel_group` s'exécutent en parallèle : leurs écritures communes ne dépendent pas de leur ordre, et aucune ne dépend d'une autre tâche du groupe.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.sources.registry import (
    DOI_SEARCHABLE_SOURCES,
    HARVESTED_SOURCES,
    PERSON_SEARCHED_SOURCES,
    PROFILES,
    SOURCE_PRIORITY,
    Source,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from pipeline.runtime.context import Phase as ExecutablePhase, PhaseContext
    from pipeline.runtime.observability.metrics import PhaseMetrics


@dataclass(frozen=True, slots=True)
class Task:
    """Tâche du pipeline, avec ses lectures et ses écritures."""

    name: str
    phase: str
    """Phase d'exécution de la tâche, pour l'affichage et la sélection."""
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    previous_run: frozenset[str] = frozenset()
    """Lectures de données écrites au run précédent, par une tâche placée après elle ou par la tâche elle-même."""
    network: str | None = None
    """API interrogée, si la tâche sort sur le réseau."""
    maintenance: tuple[str, ...] = ()
    """Maintenance physique des tables, dans l'ordre : `VACUUM staging`, `ANALYZE source_contributions`."""
    parallel_group: str | None = None
    """Groupe de tâches consécutives exécutées en parallèle."""
    run: TaskRun | None = None
    section: str | None = None
    """Titre de la sous-étape ouverte par la tâche. `None` : la tâche écrit sous le titre courant."""
    label: str | None = None
    """Libellé de la ligne de bilan. `None` : la tâche écrit elle-même ses lignes."""
    progress_bar: bool = False
    """La tâche affiche une barre d'avancement en terminal, donc sa ligne de bilan va seulement au journal."""
    threshold: int | None = None
    """Échecs consécutifs avant la coupure du circuit-breaker de la source. `None` : seuil par défaut."""
    when: Callable[[PhaseContext], bool] | None = None
    """Condition d'exécution, évaluée avant l'accès à la source. Une tâche écartée renvoie des métriques vides et n'écrit rien."""
    silent_when_empty: bool = False
    """La tâche n'écrit rien sans élément traité : `total` nul, sans signal."""


type TaskRun = Callable[[PhaseContext], PhaseMetrics]
"""Exécute une tâche dans le contexte de sa phase."""


def task(
    name: str,
    *,
    reads: Iterable[str] = (),
    writes: Iterable[str] = (),
    previous_run: Iterable[str] = (),
    run: TaskRun,
    network: str | None = None,
    maintenance: tuple[str, ...] = (),
    parallel_group: str | None = None,
    section: str | None = None,
    label: str | None = None,
    progress_bar: bool = False,
    threshold: int | None = None,
    when: Callable[[PhaseContext], bool] | None = None,
    silent_when_empty: bool = False,
) -> Task:
    """Renvoie la tâche `name`, de la phase nommée par son préfixe, exécutée par `run`."""
    return Task(
        name,
        name.partition(".")[0],
        frozenset(reads),
        frozenset(writes),
        frozenset(previous_run),
        network,
        maintenance,
        parallel_group,
        run,
        section,
        label,
        progress_bar,
        threshold,
        when,
        silent_when_empty,
    )


@dataclass(frozen=True, slots=True)
class _PhaseIo:
    """Lectures et écritures communes à toutes les tâches d'une phase."""

    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    previous_run: tuple[str, ...] = ()


_PHASE_IO: dict[str, _PhaseIo] = {
    # Identifiants des publications du périmètre, cherchés dans les autres sources ; échecs retenus dans `failed_lookups`.
    "fetch_missing": _PhaseIo(
        reads=(
            "config",
            "staging",
            "failed_lookups",
            "source_records.source",
            "source_record_identifiers",
            "source_records.publication_id",
            "publications.in_perimeter",
        ),
        writes=("staging", "staging_normalization_queue", "failed_lookups"),
        previous_run=(
            "staging",
            "failed_lookups",
            "source_records",
            "source_record_identifiers",
            "publications.in_perimeter",
        ),
    ),
}


def _task(
    name: str,
    phase: str,
    *,
    reads: Iterable[str] = (),
    writes: Iterable[str] = (),
    previous_run: Iterable[str] = (),
    network: str | None = None,
    maintenance: tuple[str, ...] = (),
    parallel_group: str | None = None,
) -> Task:
    """Renvoie une tâche de `phase`, avec les lectures et écritures communes à la phase (`_PHASE_IO`)."""
    shared = _PHASE_IO.get(phase, _PhaseIo())
    return Task(
        name,
        phase,
        frozenset((*shared.reads, *reads)),
        frozenset((*shared.writes, *writes)),
        frozenset((*shared.previous_run, *previous_run)),
        network,
        maintenance,
        parallel_group,
    )


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


def dependencies(tasks: Sequence[Task]) -> dict[str, set[str]]:
    """Renvoie, pour chaque tâche, les tâches placées avant elle, hors de son groupe parallèle, et écrivant une donnée lue par elle."""
    return {
        reader.name: {
            writer.name
            for writer in tasks[:i]
            if (reader.parallel_group is None or writer.parallel_group != reader.parallel_group)
            and _writes_read(reader, writer)
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


TASKS: tuple[Task, ...] = (
    _task(
        "perimeter_structures",
        "run",
        reads=("perimeters", "structure_parents", "structures"),
        writes=("perimeter_structures",),
    ),
    # Acquisition : les canaux écrivent la dernière version de chaque document moissonné dans `staging`, dans un ordre indifférent. Leurs lectures de `staging` dédoublonnent et valent quel que soit l'ordre.
    *(
        _task(
            f"harvest.{source}",
            "harvest",
            reads=(
                "config",
                "structures",
                "perimeters",
                "perimeter_structures",
                "staging",
                "pipeline_phase_executions",
            ),
            writes=("staging", "staging_normalization_queue"),
            previous_run=("staging", "pipeline_phase_executions"),
            network=source,
            parallel_group="harvest",
        )
        for source in HARVESTED_SOURCES
    ),
    # Interrogation par identifiant de personne : identifiants des personnes RH, posés par la phase `persons` au run précédent.
    *(
        _task(
            f"harvest_by_person.{source}",
            "harvest_by_person",
            reads=("config", "hr_records", "person_identifiers", "staging"),
            writes=("staging", "staging_normalization_queue"),
            previous_run=("staging", "person_identifiers"),
            network=source,
            parallel_group="harvest_by_person",
        )
        for source in PERSON_SEARCHED_SOURCES
    ),
    _task(
        "fetch_missing.hal_by_id",
        "fetch_missing",
        network="hal",
        parallel_group="fetch_missing.hal_id",
    ),
    _task(
        "fetch_missing.scanr_by_hal_id",
        "fetch_missing",
        reads=("source_records.source_id",),
        network="scanr",
        parallel_group="fetch_missing.hal_id",
    ),
    _task(
        "fetch_missing.hal_by_nnt",
        "fetch_missing",
        reads=("publications.doc_type",),
        previous_run=("publications.doc_type",),
        network="hal",
        parallel_group="fetch_missing.nnt",
    ),
    _task(
        "fetch_missing.theses_by_nnt",
        "fetch_missing",
        network="theses",
        parallel_group="fetch_missing.nnt",
    ),
    *(
        _task(
            f"fetch_missing.doi.{source}",
            "fetch_missing",
            # DOI candidats de la vue `candidate_dois`, bornés à la fenêtre d'années du run par les enregistrements sources de leur publication, et agence d'enregistrement pour Crossref et DataCite.
            reads=(
                "source_record_identifiers",
                "source_records.publication_year",
                "publication_relations",
                *(("doi_prefixes.ra",) if PROFILES[source].registration_agency else ()),
            ),
            previous_run=("doi_prefixes", "publication_relations"),
            network=source,
            parallel_group="fetch_missing.doi",
        )
        for source in DOI_SEARCHABLE_SOURCES
    ),
    *(
        _task(
            f"fetch_stale.{source}",
            "fetch_stale",
            reads=("config", "staging", "source_records.publication_year"),
            writes=("staging", "staging_normalization_queue"),
            previous_run=("staging", "source_records"),
            network=source,
            parallel_group="fetch_stale",
        )
        for source in Source
    ),
    *(
        _task(
            f"normalize.{source}",
            "normalize",
            reads=(
                "staging",
                "staging_normalization_queue",
                "source_records.id",
                "source_records.authors_hash",
                "source_records.publication_id",
                "source_contributions.id",
                "source_contributions.author_position",
                "source_contributions.roles",
                "source_contributions.contributor_information_id",
                "source_contributions.content_hash",
                "contributor_information",
                "addresses.id",
                "countries",
                "subjects",
                # Contributions des contributions sources à rôles ou statut de correspondant modifiés.
                "aligned_source_contributions",
            ),
            writes=(
                "staging_normalization_queue",
                "staging.raw_data",
                "source_records",
                "source_record_identifiers",
                "source_record_locations",
                "embargoes",
                "subjects",
                "source_record_subjects",
                "platforms",
                "source_contributions",
                "source_contribution_addresses",
                "source_contribution_rors",
                "source_contribution_hal_structures",
                "contributor_information",
                "addresses.id",
                "address_candidates_queue",
                "address_country_candidates",
                "publication_contributions_queue",
                "source_contribution_countries_queue",
                "source_record_keys_queue",
                "contribution_attributes_queue",
            ),
            # Ses propres lignes de `staging`, de la file de normalisation, enregistrements sources et contributions sources ; les contributions écrites par `author_grouping`.
            previous_run=(
                "staging",
                "staging_normalization_queue",
                "source_records",
                "source_record_locations",
                "embargoes",
                "subjects",
                "source_record_subjects",
                "platforms",
                "source_contributions",
                "contributor_information",
                "addresses",
                "aligned_source_contributions",
            ),
        )
        for source in SOURCE_PRIORITY
    ),
    _task(
        "normalize.prune_disappeared",
        "normalize",
        reads=(
            "staging.disappeared_at",
            "source_records.id",
            "source_records.staging_id",
            "source_records.publication_id",
        ),
        # La suppression d'un enregistrement source emporte ses localisations, ses contributions sources, leurs adresses, ROR et structures HAL, et les décisions qui les visent.
        writes=(
            "source_records.id",
            "source_record_identifiers",
            "source_record_locations",
            "embargoes",
            "source_record_subjects",
            "source_record_keys_queue",
            "publication_contributions_queue",
            "source_contributions.id",
            "source_contribution_addresses",
            "source_contribution_rors",
            "source_contribution_hal_structures",
            "confirmed_source_contributions",
            "rejected_contributions",
        ),
        previous_run=("source_records",),
    ),
    _task(
        "normalize.cleanup_orphan_contributor_information",
        "normalize",
        reads=("source_contributions.contributor_information_id", "contributor_information.id"),
        writes=("contributor_information.id",),
        previous_run=("source_contributions",),
    ),
    _task(
        "normalize.cleanup_orphan_addresses",
        "normalize",
        reads=("source_contribution_addresses", "addresses.id"),
        # La suppression d'une adresse emporte ses liens aux structures.
        writes=("addresses.id", "address_structures"),
        # La normalisation vide `staging.raw_data`. `VACUUM FULL` en mode full.
        maintenance=("VACUUM staging",),
    ),
    _task(
        "author_grouping.build",
        "author_grouping",
        reads=(
            "publications.id",
            "publication_contributions_queue",
            "source_records.publication_id",
            "source_records.source_id",
            "source_records.corrections",
            "source_contributions.id",
            "source_contributions.source_record_id",
            "source_contributions.author_position",
            "source_contributions.collective",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "contributor_information",
            # Prénom de la personne à laquelle un humain a rattaché l'identifiant d'une contribution source.
            "person_identifiers",
            "persons",
            "contributions",
            "aligned_source_contributions",
        ),
        writes=(
            "contributions.id",
            "contributions.reference_position",
            "aligned_source_contributions.id",
            "source_contributions.duplicate_of",
            "publication_contributions_queue",
            "contribution_attributes_queue",
            # Une contribution rattachée dont les contributions sources changent est marquée pour la redécision de sa personne.
            "contribution_resolution_queue",
            "publication_author_alignment",
        ),
        # Publications supprimées plus loin dans le même run par `finalize.purge_publications` ; marquages retirés par la tâche elle-même ; personnes, identifiants, neutralisations et personnes des contributions, écrits par la phase `persons`.
        previous_run=(
            "publications.id",
            "publication_contributions_queue",
            "person_identifiers",
            "persons",
            "source_contributions.neutralized_identifiers",
            "contributions.person_id",
            "contributions.resolution_mode",
        ),
    ),
    _task(
        "author_grouping.attributes",
        "author_grouping",
        reads=(
            "contribution_attributes_queue",
            "aligned_source_contributions",
            "source_contributions.is_corresponding",
            "source_contributions.perimeter_evidence",
            "source_contributions.roles",
            "source_contributions.author_position",
            "source_contributions.collective",
            "source_contributions.duplicate_of",
            "source_records.publication_id",
            "source_records.source_id",
            "contributions.id",
            "contributions.publication_id",
            "contributions.author_positions",
            "contributions.perimeter_evidence",
            "contributions.roles",
            "contributions.person_id",
            "contributions.resolution_mode",
        ),
        writes=(
            "contributions.author_positions",
            "contributions.perimeter_evidence",
            "contributions.roles",
            "contribution_attributes_queue",
            # Une contribution rattachée sans épinglage qui quitte le périmètre est marquée pour la redécision de sa personne.
            "contribution_resolution_queue",
        ),
        # Personnes des contributions, écrites par la phase `persons`.
        previous_run=(
            "contributions.person_id",
            "contributions.resolution_mode",
        ),
    ),
)


RUN_PHASE = "run"
"""Groupe des tâches exécutées par l'orchestrateur avant toute phase."""


def phase_tasks(phase: str) -> tuple[Task, ...]:
    """Renvoie les tâches de `phase` déclarées dans `TASKS`, dans leur ordre."""
    return tuple(task for task in TASKS if task.phase == phase)


@dataclass(frozen=True)
class Phase:
    """Phase du pipeline : tâches consécutives, avec leur libellé et leurs attributs."""

    name: str
    label: str
    """Libellé lisible sans connaître le schéma. Les champs entre accolades reçoivent les valeurs de `label_fields` au lancement de la phase."""
    tasks: tuple[Task, ...]
    extra: bool = False
    """Enrichissement, hors résolution d'entités : `--no-extras` l'omet."""
    harvesting: bool = False
    """Moissonnage : le journal de la phase se termine par le total de ses sources."""
    label_fields: Callable[[Connection], dict[str, str]] | None = None
    """Valeurs des champs du libellé, lues dans la configuration."""
    check: Callable[[PhaseContext], None] | None = None
    """Précondition, vérifiée avant les tâches : lève une exception si elle n'est pas remplie."""
    assemble: Callable[[Mapping[str, PhaseMetrics]], PhaseMetrics] | None = None
    """Métriques de la phase, d'après celles de ses tâches, par nom de tâche. `None` : leur somme."""
    build: Callable[[], ExecutablePhase] | None = None
    """Construction de la phase exécutée par sa propre classe."""
