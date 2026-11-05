#!/usr/bin/env python
"""Orchestrateur du pipeline bibliométrique : sélection et séquence d'exécution des phases.

`pipeline.phases.PHASES` donne les phases dans l'ordre d'exécution, avec leur libellé et leurs attributs.

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
from collections.abc import Sequence
from dataclasses import dataclass
from types import FrameType
from typing import NoReturn, cast

from domain.pipeline_runs import PhaseStatus
from domain.sources.registry import Source
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
from pipeline.graph import Phase
from pipeline.ingestion.api_params import request_budget
from pipeline.ingestion.credentials import source_credentials_missing
from pipeline.phases import PERIMETER_STRUCTURES, PHASES
from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.runtime.execution import log, phase_context
from pipeline.runtime.lock import PipelineAlreadyRunningError, pipeline_lock
from pipeline.runtime.modes import MODE_NAMES
from pipeline.runtime.observability.exception_chain import failure_message, is_user_interruption
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import set_bar_stream, write_above_bars
from pipeline.task_runner import run_phase

set_console_writer(write_above_bars)
set_bar_stream(console_stream())

# Seuil du root logger, destinataire des modules qui appellent `logging.getLogger(__name__)` : les bibliothèques tierces y écrivent trop d'informations pour les laisser passer.
configure_root_logging(logging.WARNING)


PHASE_NAMES = [phase.name for phase in PHASES]


def _sigterm_raises_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _install_sigterm_handler() -> None:
    """Convertit SIGTERM en KeyboardInterrupt : un arrêt par systemd ou `docker stop` journalise la phase interrompue et la commande de reprise.

    Sans effet sur Windows, où `os.kill` ne délivre pas SIGTERM.
    """
    signal.signal(signal.SIGTERM, _sigterm_raises_keyboard_interrupt)


def _catalogue_des_phases() -> str:
    """Renvoie les phases dans l'ordre d'exécution, chacune avec son libellé."""
    width = max(len(name) for name in PHASE_NAMES)
    lines = ["Phases, dans l'ordre :"]
    for i, phase in enumerate(PHASES, 1):
        lines.append(f"  {i:2d}. {phase.name:{width}s}  {phase.label}")
    return "\n".join(lines)


def _source_list(value: str) -> frozenset[str]:
    """Valide `--sources` : au moins une source, toutes connues du registre."""
    sources = [s.strip() for s in value.split(",") if s.strip()]
    if not sources:
        raise argparse.ArgumentTypeError("au moins une source attendue")
    if unknown := [s for s in sources if s not in Source]:
        raise argparse.ArgumentTypeError(f"source(s) inconnue(s) : {', '.join(unknown)}")
    return frozenset(sources)


class _YearRange(argparse.Action):
    """Lit `--years` : une année, ou la première et la dernière d'une plage."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[object] | None,
        option_string: str | None = None,
    ) -> None:
        years = cast("list[int]", values)
        if len(years) > 2:
            parser.error("--years : une année, ou la première et la dernière d'une plage")
        first, last = years[0], years[-1]
        if first > last:
            parser.error(f"--years : {first} est postérieure à {last}")
        setattr(namespace, self.dest, (first, last))


@dataclass(frozen=True)
class _RunFlag:
    """Option booléenne de la CLI, transmise aux phases par le champ homonyme de `RunOptions`."""

    option: str
    help: str
    banner: str | None = None
    """Libellé de l'option dans la bannière du run, ou `None` pour l'omettre."""

    @property
    def dest(self) -> str:
        return self.option.removeprefix("--").replace("-", "_")


_RUN_FLAGS = (
    _RunFlag(
        "--include-wos",
        "Inclure WoS dans le moissonnage et la phase fetch_missing (source exclue par défaut : "
        "en fin de vie, crédit API limité).",
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
        "À la phase publications, reconstruit toutes les publications, pour appliquer une "
        "évolution des règles de clés sur tout le stock.",
        "publications reconstruites",
    ),
    _RunFlag(
        "--rebuild-author-grouping",
        "À la phase author_grouping, marque toutes les publications à regrouper, pour appliquer "
        "une évolution des règles d'alignement des auteurs sur tout le stock.",
        "alignement des auteurs reconstruit",
    ),
    _RunFlag(
        "--rebuild-persons",
        "À la phase persons, redécide toutes les contributions rattachées hors épinglage, contre "
        "les personnes existantes, pour appliquer une évolution des règles de rattachement sur "
        "tout le stock.",
        "rattachements des personnes redécidés",
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
    """Renvoie le parseur des arguments de `run_pipeline`. L'aide liste les phases, nommées par `--from` et `--only`."""
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
        default=frozenset(Source),
        help=f"Sources, séparées par des virgules (défaut : {','.join(Source)})",
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        action=_YearRange,
        metavar="ANNÉE",
        help="Une année, ou la première et la dernière d'une plage (défaut : de la clé de "
        "configuration pipeline_start_year_full à l'année courante)",
    )
    for flag in _RUN_FLAGS:
        parser.add_argument(flag.option, action="store_true", help=flag.help)
    return parser


def _run_options(args: argparse.Namespace) -> RunOptions:
    """Renvoie les options du run transmises aux phases."""
    return RunOptions(
        mode=args.mode,
        sources=args.sources,
        years=args.years,
        **{flag.dest: getattr(args, flag.dest) for flag in _RUN_FLAGS},
    )


def _select_phases_to_run(args: argparse.Namespace) -> list[Phase]:
    """Renvoie les phases à exécuter selon `--only` ou `--from` (sinon toutes), moins les enrichissements avec `--no-extras`.

    Une phase nommée par `--only` est renvoyée même si c'est un enrichissement.
    """
    if args.only:
        return [phase for phase in PHASES if phase.name == args.only]
    selected = list(PHASES[PHASE_NAMES.index(args.from_phase) :] if args.from_phase else PHASES)
    if args.no_extras:
        selected = [phase for phase in selected if not phase.extra]
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


def _phase_title(name: str, label: str) -> list[str]:
    """Renvoie les lignes d'ouverture d'une phase : son nom et son libellé."""
    return _framed([f"{PHASE_MARKER}{name}", label])


PIPELINE_TITLE = (
    "┏┓ ╻┏┓ ╻  ╻┏━┓┏┳┓┏━╸╺┳╸┏━┓╻┏━╸",
    "┣┻┓┃┣┻┓┃  ┃┃ ┃┃┃┃┣╸  ┃ ┣┳┛┃┣╸",
    "┗━┛╹┗━┛┗━╸╹┗━┛╹ ╹┗━╸ ╹ ╹┗╸╹┗━╸",
)
"""« BIBLIOMETRIE » en caractères de filets, en tête de la bannière d'une exécution."""

_SETTING_KEY_WIDTH = 9
"""Largeur d'une clé de réglage et de ses points de conduite, dans la bannière."""


def _setting(key: str, value: str) -> list[str]:
    """Renvoie les lignes « clé ···· valeur » de la bannière, la valeur repliée sous elle-même."""
    head = f"{key} {'·' * (_SETTING_KEY_WIDTH - len(key))} "
    wrapped = textwrap.wrap(value, PHASE_TITLE_WIDTH - len(head)) or [""]
    return [head + wrapped[0], *(" " * len(head) + continuation for continuation in wrapped[1:])]


def _banner(settings: list[str]) -> list[str]:
    """Encadre le titre et les réglages d'une exécution, avec une ombre.

    Un terminal reçoit le cadre, au moins aussi large que celui d'une phase. Une sortie capturée reçoit deux filets et le titre en texte.
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


def _run_title(args: argparse.Namespace, phases: list[Phase]) -> list[str]:
    """Renvoie les lignes d'ouverture d'une exécution : son mode, puis ses réglages distincts du lancement par défaut."""
    settings = _setting("mode", args.mode)

    if args.years:
        first, last = args.years
        if first == last:
            settings += _setting("année", str(first))
        else:
            settings += _setting("années", f"{first}-{last}")

    if args.only or args.from_phase:
        settings += _setting("phases", ", ".join(phase.name for phase in phases))
    elif args.no_extras:
        settings += _setting("phases", "sans les enrichissements terminaux")

    options = [flag.banner for flag in _RUN_FLAGS if flag.banner and getattr(args, flag.dest)]
    if options:
        settings += _setting("options", ", ".join(options))

    return _banner(settings)


def _context(options: RunOptions) -> PhaseContext:
    """Renvoie un contexte d'exécution, avec l'accès aux identifiants et au débit des sources."""
    return phase_context(
        options, credentials_missing=source_credentials_missing, request_budget=request_budget
    )


def _run_one_phase(
    phase: Phase, *, options: RunOptions, recorder: PhaseExecutionRecorder
) -> tuple[str, float]:
    """Exécute une phase et enregistre son observabilité. Renvoie son nom et sa durée.

    Une interruption clavier ou une exception est enregistrée, puis termine le processus. `--from <phase>` reprend la séquence à la phase interrompue.
    """
    name = phase.name
    # Le nom de la phase préfixe les records émis pendant la phase, y compris par les moissonneurs en threads, qui héritent du contexte.
    phase_token = set_log_phase(name)
    try:
        # Ligne vide devant le cadre, pour le séparer de la sortie de la phase précédente.
        log.info("")
        for line in _phase_title(name, phase.label):
            log.info("%s", line)
        phase_started_at = datetime.datetime.now(datetime.UTC)
        t0_phase = time.time()
        ctx = _context(options)
        try:
            metrics = run_phase(phase, ctx)
        except (KeyboardInterrupt, Exception) as e:
            _stop_on_failure(
                e,
                phase=name,
                started_at=phase_started_at,
                duration=time.time() - t0_phase,
                ctx=ctx,
                recorder=recorder,
            )

        duration = time.time() - t0_phase
        if phase.harvesting:
            log.info("")
            log.info("Total : %s", metrics.as_summary())
        recorder.record(
            phase=name,
            started_at=phase_started_at,
            status=PhaseStatus.WARNING if metrics.signals else PhaseStatus.OK,
            metrics=metrics.to_payload(duration, ctx.task_durations),
            signals=metrics.signals,
            details=metrics.details,
        )
        return (name, duration)
    finally:
        reset_log_phase(phase_token)


def _stop_on_failure(
    error: BaseException,
    *,
    phase: str,
    started_at: datetime.datetime,
    duration: float,
    ctx: PhaseContext,
    recorder: PhaseExecutionRecorder,
) -> NoReturn:
    """Journalise l'échec de la phase et la commande de reprise, enregistre la phase en échec, puis termine le processus."""
    # Une interruption en pleine requête invalide la connexion : le nettoyage suivant lève une erreur SQLAlchemy, et le `KeyboardInterrupt` reste dans la chaîne des exceptions.
    interrupted = is_user_interruption(error)
    if interrupted:
        message = "Interrompu par l'utilisateur (action contrôlée)"
        log.warning("Pipeline interrompu par l'utilisateur à la phase '%s'", phase)
    else:
        message = failure_message(error)
        log.error("Pipeline interrompu à la phase '%s' : %s", phase, message)
        log.error("Trace de l'échec", exc_info=error, extra={"detail": True})
    log.log(
        logging.INFO if interrupted else logging.ERROR,
        "Pour reprendre : run_pipeline --from %s",
        phase,
    )
    status = PhaseStatus.WARNING if interrupted else PhaseStatus.ERROR
    recorder.record(
        phase=phase,
        started_at=started_at,
        status=status,
        metrics=PhaseMetrics().to_payload(duration, ctx.task_durations),
        signals=[
            {
                "level": status,
                "code": "interrupted" if interrupted else "exception",
                "message": message,
            }
        ],
        details={},
    )
    sys.exit(130 if interrupted else 1)


def _execute_phases(options: RunOptions, phases_to_run: list[Phase]) -> None:
    """Déroule la séquence des phases avec observabilité par run, puis le récapitulatif de fin."""
    # Enregistre le run et chacune de ses phases : identifiant de séquence, entrées, sorties, statut.
    recorder = start_run(
        mode=options.mode, sources=[s for s in Source if s in options.queried_sources]
    )
    if recorder.run_id is not None:
        log.info("%s%d", RUN_MARKER, recorder.run_id)

    # Avant toute phase, même avec `--only` ou `--from` : les phases lisent le périmètre sans le recalculer.
    PERIMETER_STRUCTURES.run(_context(options))

    t0_total = time.time()
    phase_results = [
        _run_one_phase(phase, options=options, recorder=recorder) for phase in phases_to_run
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
    # Sur une faute de segmentation dans une extension C, `faulthandler` écrit la pile de chaque thread sur la sortie d'erreur. Il exige un vrai descripteur de fichier, absent sous la sortie capturée d'un test.
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
            _execute_phases(_run_options(args), phases_to_run)
    except PipelineAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
