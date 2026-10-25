#!/usr/bin/env python
"""Orchestrateur du pipeline bibliométrique : sélection et séquence d'exécution des phases.

Le module de chaque phase expose `build`, qui câble ses dépendances et rend la phase prête à s'exécuter. `PHASE_ORDER` fixe l'ordre d'exécution et `_PHASE_BUILDERS` associe chaque nom à sa fonction `build`.

`run_pipeline --help` donne les options et la liste des phases.
"""

import argparse
import contextlib
import datetime
import faulthandler
import io
import logging
import signal
import sys
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import FrameType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Connection

from domain.config import ConfigKey
from domain.sources.registry import ALL_SOURCES
from infrastructure.observability.log import (
    PHASE_MARKER,
    RUN_END_MARKER,
    RUN_MARKER,
    configure_root_logging,
    console_stream,
    reset_log_phase,
    set_console_writer,
    set_log_phase,
)
from infrastructure.observability.phase_executions import PhaseExecutionRecorder, start_run
from pipeline.graph import EXTRA_PHASES, HARVESTING_PHASES, PHASE_LABELS, PHASE_ORDER
from pipeline.ingestion.api_params import request_budget
from pipeline.ingestion.common import (
    fetch_missing,
    fetch_stale,
    harvest,
    harvest_by_person,
    normalize,
)
from pipeline.ingestion.credentials import source_credentials_missing
from pipeline.ingestion.openalex import fetch_truncated
from pipeline.runtime.config import delay
from pipeline.runtime.context import Phase, RunOptions
from pipeline.runtime.execution import log, open_tx, phase_context
from pipeline.runtime.lock import PipelineAlreadyRunningError, pipeline_lock
from pipeline.runtime.modes import MODE_NAMES
from pipeline.runtime.observability.exception_chain import failure_message, is_user_interruption
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import set_bar_stream, write_above_bars
from pipeline.runtime.observability.signals import select_targets
from pipeline.transformation import finalize
from pipeline.transformation.countries import countries
from pipeline.transformation.persons import persons
from pipeline.transformation.publications import oa_status, publications, relations
from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.correction import metadata_correction
from pipeline.transformation.publications.subjects import subjects
from pipeline.transformation.publishing import publishing, resolve_ra
from pipeline.transformation.structures import affiliations
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures

set_console_writer(write_above_bars)
set_bar_stream(console_stream())

# Seuil du root logger, où émettent les modules qui appellent `logging.getLogger(__name__)` :
# les bibliothèques tierces y écrivent trop d'information pour la laisser passer.
configure_root_logging(logging.WARNING)


# Une phase se construit sans argument : elle reçoit les options du run par son contexte d'exécution.
type PhaseBuilder = Callable[[], Phase]

# Construction de chaque phase. `PHASE_ORDER` fixe l'ordre d'exécution ; un contrôle au
# démarrage vérifie que le registre couvre exactement les phases qu'il nomme.
_PHASE_BUILDERS: dict[str, PhaseBuilder] = {
    "harvest": harvest.build,
    "harvest_by_person": harvest_by_person.build,
    "resolve_ra": resolve_ra.build,
    "fetch_missing": fetch_missing.build,
    "fetch_stale": fetch_stale.build,
    "fetch_truncated": fetch_truncated.build,
    "normalize": normalize.build,
    "affiliations": affiliations.build,
    "publishing": publishing.build,
    "metadata_correction": metadata_correction.build,
    "publications": publications.build,
    "author_grouping": author_grouping.build,
    "relations": relations.build,
    "persons": persons.build,
    "finalize": finalize.build,
    "countries": countries.build,
    "subjects": subjects.build,
    "oa_status": oa_status.build,
}

if set(_PHASE_BUILDERS) != set(PHASE_ORDER):
    raise RuntimeError(
        "Le registre des phases de l'orchestrateur et `PHASE_ORDER` divergent : "
        f"{set(_PHASE_BUILDERS) ^ set(PHASE_ORDER)}"
    )

PHASES: list[tuple[str, PhaseBuilder]] = [(name, _PHASE_BUILDERS[name]) for name in PHASE_ORDER]

PHASE_NAMES = list(PHASE_ORDER)


def _sigterm_raises_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _install_sigterm_handler() -> None:
    """Convertit SIGTERM en KeyboardInterrupt, traité comme une interruption clavier : ligne de journal, rapport partiel, commande de reprise.

    Un arrêt demandé par systemd, `docker stop` ou `kubectl delete` laisse ainsi la trace du point où le pipeline s'est arrêté. Sur Windows, où `os.kill` ne délivre pas SIGTERM, la fonction reste sans effet.
    """
    signal.signal(signal.SIGTERM, _sigterm_raises_keyboard_interrupt)


def _catalogue_des_phases() -> str:
    """Phases dans l'ordre d'exécution, chacune résumée par la première ligne de la docstring de sa fonction `build`."""
    width = max(len(name) for name, _ in PHASES)
    lines = ["Phases, dans l'ordre :"]
    for i, (name, build) in enumerate(PHASES, 1):
        doc = build.__doc__.strip().split("\n")[0] if build.__doc__ else ""
        lines.append(f"  {i:2d}. {name:{width}s}  {doc}")
    return "\n".join(lines)


def _source_list(value: str) -> str:
    """Valide `--sources` : au moins une source, toutes connues du registre."""
    sources = [s.strip() for s in value.split(",") if s.strip()]
    if not sources:
        raise argparse.ArgumentTypeError("au moins une source attendue")
    if unknown := [s for s in sources if s not in ALL_SOURCES]:
        raise argparse.ArgumentTypeError(f"source(s) inconnue(s) : {', '.join(unknown)}")
    return ",".join(sources)


@dataclass(frozen=True)
class _RunFlag:
    """Option booléenne de la CLI, transmise aux phases par le champ homonyme de `RunOptions`."""

    option: str
    help: str
    banner: str | None = None
    """Libellé de l'option dans la bannière du run ; sans libellé, l'option n'y paraît pas."""

    @property
    def dest(self) -> str:
        return self.option.removeprefix("--").replace("-", "_")


_RUN_FLAGS = (
    _RunFlag(
        "--include-wos",
        "Inclure WoS dans l'extraction et la phase fetch_missing (opt-in : source en fin de vie, "
        "crédit API limité ; exclue par défaut).",
    ),
    _RunFlag(
        "--raw-store",
        "Archive les réponses brutes des sources sur disque, sous `BIBLIO_RAW_STORE_DIR`. Rejouer "
        "une normalisation puise alors dans cette archive au lieu de réinterroger les sources.",
        "archivage des données brutes",
    ),
    _RunFlag(
        "--normalize-full",
        "À la phase normalize, marque tous les enregistrements sources des sources normalisées : "
        "chacun resynchronise ses contributions sources à sa prochaine normalisation, même si son "
        "bloc auteurs est inchangé. Sert à appliquer une règle de normalisation des auteurs modifiée.",
        "contributions sources resynchronisées",
    ),
    _RunFlag(
        "--rebuild-publications",
        "Avant la phase publications, re-dirtie tout le stock (rebuild complet : "
        "cluster-then-materialize global). À utiliser après une évolution des règles de clés.",
        "publications reconstruites",
    ),
    _RunFlag(
        "--rebuild-author-grouping",
        "À la phase author_grouping, marque toutes les publications à regrouper, pour appliquer "
        "une évolution des règles d'alignement des auteurs sur tout le stock.",
        "alignement des auteurs reconstruit",
    ),
    _RunFlag(
        "--rebuild-subjects",
        "À la phase subjects, marque toutes les publications à ingérer, pour propager "
        "une évolution des règles d'ingestion sur tout le stock.",
        "sujets reconstruits",
    ),
)
"""Options booléennes du run, dans l'ordre des phases qu'elles touchent."""


def _build_arg_parser() -> argparse.ArgumentParser:
    """Parseur des arguments de la CLI pipeline.

    L'aide porte le catalogue des phases : `--from` et `--only` les nomment.
    """
    parser = argparse.ArgumentParser(
        description="Orchestrateur pipeline bibliométrique",
        epilog=_catalogue_des_phases(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--from",
        dest="from_phase",
        metavar="PHASE",
        choices=PHASE_NAMES,
        help="Reprendre depuis cette phase",
    )
    parser.add_argument(
        "--only",
        metavar="PHASE",
        choices=PHASE_NAMES,
        help="Exécuter uniquement cette phase",
    )
    parser.add_argument(
        "--no-extras",
        action="store_true",
        help="Omettre les enrichissements terminaux (relations, subjects, countries, oa_status)",
    )
    parser.add_argument(
        "--mode", choices=list(MODE_NAMES), default="full", help="Mode d'exécution (défaut: full)"
    )
    parser.add_argument(
        "--sources",
        type=_source_list,
        default=",".join(ALL_SOURCES),
        help=f"Sources, séparées par des virgules (défaut : {','.join(ALL_SOURCES)})",
    )
    parser.add_argument(
        "--year", type=int, help="Surcharger l'année d'extraction (une seule année)"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="Année de début du range d'extraction (mode full ; défaut: config "
        "pipeline_start_year_full)",
    )
    for flag in _RUN_FLAGS:
        parser.add_argument(flag.option, action="store_true", help=flag.help)
    return parser


def _run_options(args: argparse.Namespace, sources: set[str]) -> RunOptions:
    """Options du run transmises aux phases."""
    return RunOptions(
        mode=args.mode,
        sources=frozenset(sources),
        year=args.year,
        start_year=args.start_year,
        **{flag.dest: getattr(args, flag.dest) for flag in _RUN_FLAGS},
    )


def _select_phases_to_run(
    args: argparse.Namespace,
) -> list[tuple[str, PhaseBuilder]]:
    """Phases à exécuter selon `--only` / `--from` (sinon toutes), moins les enrichissements si `--no-extras`.

    `--only` nomme une phase explicitement : elle est rendue même si c'est un enrichissement.
    """
    if args.only:
        return [(n, build) for n, build in PHASES if n == args.only]
    if args.from_phase:
        selected = PHASES[PHASE_NAMES.index(args.from_phase) :]
    else:
        selected = list(PHASES)
    if args.no_extras:
        selected = [(n, build) for n, build in selected if n not in EXTRA_PHASES]
    return selected


PHASE_TITLE_WIDTH = 48
"""Largeur du texte dans le cadre d'un titre, la même pour tous."""


def _framed(lines: list[str]) -> list[str]:
    """Encadre `lines`, chacune repliée à la largeur du cadre.

    Un terminal reçoit un cadre de largeur constante, une sortie capturée deux filets horizontaux.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, *lines, "─" * 40]

    wrapped_lines = [
        wrapped for line in lines for wrapped in textwrap.wrap(line, PHASE_TITLE_WIDTH)
    ]
    width = PHASE_TITLE_WIDTH + 4
    return [
        f"╔{'═' * width}╗",
        *[f"║  {line.ljust(width - 2)}║" for line in wrapped_lines],
        f"╚{'═' * width}╝",
    ]


def _fetch_stale_fields(conn: "Connection") -> dict[str, str]:
    return {"delai": quantity(delay(conn, ConfigKey.FETCH_STALE_AFTER_DAYS), "jour")}


_LABEL_FIELDS: dict[str, Callable[["Connection"], dict[str, str]]] = {
    "fetch_stale": _fetch_stale_fields,
}
"""Valeurs des champs de chaque libellé de phase qui en porte, lues en configuration."""


def _phase_label(name: str) -> str | None:
    """Ce que la phase produit, ses champs remplis par la configuration."""
    # `PHASE_LABELS` couvre les phases du pipeline ; les tests en nomment d'autres.
    label = PHASE_LABELS.get(name)
    fields = _LABEL_FIELDS.get(name)
    if label is None or fields is None:
        return label
    with open_tx() as conn:
        return label.format(**fields(conn))


def _phase_title(name: str, label: str | None) -> list[str]:
    """Lignes ouvrant une phase : son nom, et ce qu'elle produit."""
    return _framed([f"{PHASE_MARKER}{name}", *([label] if label else [])])


PIPELINE_TITLE = (
    "┏┓ ╻┏┓ ╻  ╻┏━┓┏┳┓┏━╸╺┳╸┏━┓╻┏━╸",
    "┣┻┓┃┣┻┓┃  ┃┃ ┃┃┃┃┣╸  ┃ ┣┳┛┃┣╸",
    "┗━┛╹┗━┛┗━╸╹┗━┛╹ ╹┗━╸ ╹ ╹┗╸╹┗━╸",
)
"""« BIBLIOMETRIE » en caractères de filets, en tête de la bannière d'une exécution."""

_SETTING_KEY_WIDTH = 9
"""Largeur d'une clé de réglage et de ses points de conduite, dans la bannière."""


def _setting(key: str, value: str) -> list[str]:
    """Lignes « clé ···· valeur » de la bannière, la valeur repliée sous elle-même."""
    head = f"{key} {'·' * (_SETTING_KEY_WIDTH - len(key))} "
    wrapped = textwrap.wrap(value, PHASE_TITLE_WIDTH - len(head)) or [""]
    return [head + wrapped[0], *(" " * len(head) + continuation for continuation in wrapped[1:])]


def _banner(settings: list[str]) -> list[str]:
    """Encadre le titre et les réglages d'une exécution, avec une ombre.

    Un terminal reçoit le cadre, au moins aussi large que celui d'une phase ; une sortie capturée reçoit deux filets et le titre en texte.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, "PIPELINE BIBLIOMÉTRIQUE", *settings, "─" * 40]

    settings = [f"  {setting}" for setting in settings]
    drawing_width = max(map(len, PIPELINE_TITLE))
    width = max(
        PHASE_TITLE_WIDTH + 4, drawing_width + 4, *(len(setting) + 2 for setting in settings)
    )
    # Un même retrait pour toutes les lignes du dessin : centrées une à une, elles se décaleraient.
    indent = " " * ((width - drawing_width) // 2)
    body = ["", *(indent + line for line in PIPELINE_TITLE), "", *settings, ""]
    tab = "┤ PIPELINE ├"
    return [
        f"┌───{tab}{'─' * (width - 3 - len(tab))}┐",
        *(f"│{line.ljust(width)}│▒" for line in body),
        f"└{'─' * width}┘▒",
        f" {'▒' * (width + 2)}",
    ]


def _run_title(args: argparse.Namespace, phases: list[tuple[str, PhaseBuilder]]) -> list[str]:
    """Lignes ouvrant une exécution : son mode, puis ce qui écarte le lancement du courant."""
    settings = _setting("mode", args.mode)

    if args.year:
        settings += _setting("année", str(args.year))
    elif args.start_year:
        settings += _setting("depuis", str(args.start_year))

    if args.only or args.from_phase:
        settings += _setting("phases", ", ".join(n for n, _ in phases))
    elif args.no_extras:
        settings += _setting("phases", "sans les enrichissements terminaux")

    options = [flag.banner for flag in _RUN_FLAGS if flag.banner and getattr(args, flag.dest)]
    if options:
        settings += _setting("options", ", ".join(options))

    return _banner(settings)


def _run_one_phase(
    name: str,
    build: PhaseBuilder,
    *,
    args: argparse.Namespace,
    sources: set[str],
    recorder: PhaseExecutionRecorder,
) -> tuple[str, float]:
    """Construit et exécute une phase, et enregistre son observabilité. Rend son nom et sa durée.

    Une interruption clavier ou une exception est enregistrée, puis termine le processus ; `--from <phase>` reprend la séquence où elle s'est arrêtée."""
    # Injecte le nom de phase dans tous les records émis pendant la phase (logger `normalize:`
    # plutôt que `pipeline:`), y compris depuis les moissonneurs threadés qui héritent du contexte.
    phase_token = set_log_phase(name)
    try:
        # Ligne vide devant le cadre : elle le détache de ce que la phase précédente a écrit.
        log.info("")
        for line in _phase_title(name, _phase_label(name)):
            log.info("%s", line)
        phase_started_at = datetime.datetime.now(datetime.UTC)
        t0_phase = time.time()
        try:
            result = build().run(
                phase_context(
                    _run_options(args, sources),
                    credentials_missing=source_credentials_missing,
                    request_budget=request_budget,
                )
            )
        except (KeyboardInterrupt, Exception) as e:
            # Une interruption en pleine requête invalide la connexion : le nettoyage qui suit lève une erreur SQLAlchemy à la place du `KeyboardInterrupt`, que la chaîne des exceptions garde.
            interrupted = is_user_interruption(e)
            if interrupted:
                message = "Interrompu par l'utilisateur (action contrôlée)"
                log.warning("Pipeline interrompu par l'utilisateur à la phase '%s'", name)
            else:
                message = failure_message(e)
                log.error("Pipeline interrompu à la phase '%s' : %s", name, message)
                log.error("Trace de l'échec", exc_info=e, extra={"detail": True})
            log.log(
                logging.INFO if interrupted else logging.ERROR,
                "Pour reprendre : run_pipeline --from %s",
                name,
            )
            recorder.record(
                phase=name,
                started_at=phase_started_at,
                status="warning" if interrupted else "error",
                metrics=PhaseMetrics().to_payload(time.time() - t0_phase),
                signals=[
                    {
                        "level": "warning" if interrupted else "error",
                        "code": "interrupted" if interrupted else "exception",
                        "message": message,
                    }
                ],
                details={},
            )
            sys.exit(130 if interrupted else 1)

        duration = time.time() - t0_phase
        metrics = result if isinstance(result, PhaseMetrics) else PhaseMetrics()
        if name in HARVESTING_PHASES:
            log.info("")
            log.info("Total : %s", metrics.as_summary())
        recorder.record(
            phase=name,
            started_at=phase_started_at,
            status="warning" if metrics.signals else "ok",
            metrics=metrics.to_payload(duration),
            signals=metrics.signals,
            details=metrics.details,
        )
        return (name, duration)
    finally:
        reset_log_phase(phase_token)


def _execute_phases(
    args: argparse.Namespace, phases_to_run: list[tuple[str, PhaseBuilder]]
) -> None:
    """Déroule la séquence des phases avec observabilité par run, puis le récapitulatif de fin."""
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}

    # Enregistre le run et chacune de ses phases : identifiant de séquence, entrées, sorties, statut.
    recorder = start_run(
        mode=args.mode,
        sources=select_targets(ALL_SOURCES, sources, include_wos=args.include_wos),
    )
    if recorder.run_id is not None:
        log.info("%s%d", RUN_MARKER, recorder.run_id)

    # Matérialise `perimeter_structures` avant toute phase, même avec `--only` ou `--from` :
    # les phases qui suivent lisent le périmètre sans le recalculer.

    with open_tx() as perimeter_conn:
        refresh_perimeter_structures(perimeter_conn)

    t0_total = time.time()
    phase_results = [
        _run_one_phase(name, build, args=args, sources=sources, recorder=recorder)
        for name, build in phases_to_run
    ]

    elapsed_total = time.time() - t0_total
    recorder.close()
    log.info("=" * 60)
    log.info("%s en %.0fs (%.1f min)", RUN_END_MARKER, elapsed_total, elapsed_total / 60)
    if recorder.run_id is not None:
        log.info("Run #%d — récapitulatif par phase :", recorder.run_id)
        for phase_name, phase_duration in phase_results:
            log.info("  %-22s %7.1fs", phase_name, phase_duration)
    log.info("=" * 60)


def main() -> None:
    # Une faute de segmentation vient d'une extension C — pilote de base, client HTTP, automate
    # de matching — et tue le processus sans passer par Python. `faulthandler` écrit alors la pile
    # de chaque thread sur la sortie d'erreur. Il lui faut un vrai descripteur de fichier, que la
    # sortie capturée d'un test ne donne pas.
    with contextlib.suppress(ValueError, io.UnsupportedOperation):
        faulthandler.enable()
    _install_sigterm_handler()
    args = _build_arg_parser().parse_args()

    phases_to_run = _select_phases_to_run(args)
    log.info("")
    for line in _run_title(args, phases_to_run):
        log.info("%s", line)
    log.info("")

    # Une seule exécution à la fois sur la base : deux en parallèle s'interbloquent.
    try:
        with pipeline_lock():
            _execute_phases(args, phases_to_run)
    except PipelineAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
