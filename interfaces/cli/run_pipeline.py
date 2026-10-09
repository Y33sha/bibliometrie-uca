#!/usr/bin/env python
"""Orchestrateur du pipeline bibliométrique : sélection et séquence d'exécution des phases.

Le module `interfaces/cli/phases/<phase>.py` de chaque phase expose `build`, qui câble ses adaptateurs et rend la phase prête à s'exécuter ; `run(ctx)` délègue la séquence à `application/pipeline/<phase>/`. `PHASE_ORDER` fixe l'ordre d'exécution et `_PHASE_BUILDERS` associe chaque nom à sa fonction `build`.

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
from types import FrameType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Connection

from application.pipeline.context import Phase, RunOptions
from application.pipeline.exception_chain import failure_message, is_user_interruption
from application.pipeline.libelles import accord
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODE_NAMES
from application.pipeline.phase_order import EXTRA_PHASES, PHASE_LIBELLES, PHASE_ORDER
from application.pipeline.progression import ecrire_hors_barre, set_flux_barres
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
from infrastructure.observability.phase_executions import PhaseExecutionRecorder
from infrastructure.pipeline_lock import PipelineAlreadyRunningError, pipeline_lock
from interfaces.cli.phases import (
    affiliations,
    authorships,
    countries,
    extract,
    fetch_missing,
    fetch_stale,
    fetch_truncated,
    metadata_correction,
    normalize,
    oa_status,
    persons,
    publications,
    publishers_journals,
    relations,
    resolve_ra,
    subjects,
)
from interfaces.cli.phases.execution import log, open_tx, phase_context

set_console_writer(ecrire_hors_barre)
set_flux_barres(console_stream())

# Seuil du root logger, où émettent les modules qui appellent `logging.getLogger(__name__)` :
# les bibliothèques tierces y écrivent trop d'information pour la laisser passer.
configure_root_logging(logging.WARNING)


# Une phase se construit sans argument : elle reçoit les options du run par son contexte d'exécution.
type PhaseBuilder = Callable[[], Phase]

# Construction de chaque phase. `PHASE_ORDER` fixe l'ordre d'exécution ; un contrôle au
# démarrage vérifie que le registre couvre exactement les phases qu'il nomme.
_PHASE_BUILDERS: dict[str, PhaseBuilder] = {
    "extract": extract.build,
    "resolve_ra": resolve_ra.build,
    "fetch_missing": fetch_missing.build,
    "fetch_stale": fetch_stale.build,
    "fetch_truncated": fetch_truncated.build,
    "normalize": normalize.build,
    "affiliations": affiliations.build,
    "publishers_journals": publishers_journals.build,
    "metadata_correction": metadata_correction.build,
    "publications": publications.build,
    "relations": relations.build,
    "persons": persons.build,
    "authorships": authorships.build,
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
    largeur = max(len(name) for name, _ in PHASES)
    lignes = ["Phases, dans l'ordre :"]
    for i, (name, build) in enumerate(PHASES, 1):
        doc = build.__doc__.strip().split("\n")[0] if build.__doc__ else ""
        lignes.append(f"  {i:2d}. {name:{largeur}s}  {doc}")
    return "\n".join(lignes)


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
    parser.add_argument(
        "--include-wos",
        action="store_true",
        help="Inclure WoS dans l'extraction et la phase fetch_missing (opt-in : source en fin de vie, "
        "crédit API limité ; exclue par défaut).",
    )
    parser.add_argument(
        "--rebuild-publications",
        action="store_true",
        help="Avant la phase publications, re-dirtie tout le stock (rebuild complet : "
        "cluster-then-materialize global). À utiliser après une évolution des règles de clés.",
    )
    parser.add_argument(
        "--rebuild-authorships",
        action="store_true",
        help="Avant la phase authorships, purge complète de la table puis reconstruction "
        "depuis zéro (filet anti-divergence, en récupération).",
    )
    parser.add_argument(
        "--raw-store",
        action="store_true",
        help="Archive les réponses brutes des sources sur disque, sous "
        "`BIBLIO_RAW_STORE_DIR`. Rejouer une normalisation puise alors dans cette archive "
        "au lieu de réinterroger les sources.",
    )
    parser.add_argument(
        "--normalize-full",
        action="store_true",
        help="À la phase normalize, synchronise les signatures de chaque notice même si son bloc "
        "auteurs est inchangé, pour appliquer une règle de normalisation des auteurs modifiée.",
    )
    parser.add_argument(
        "--rebuild-subjects",
        action="store_true",
        help="À la phase subjects, ré-ingère toutes les publications (pas seulement les "
        "modifiées) pour propager une évolution des règles d'ingestion sur tout le stock.",
    )
    return parser


def _select_phases_to_run(
    args: argparse.Namespace,
) -> list[tuple[str, PhaseBuilder]]:
    """Phases à exécuter selon `--only` / `--from` (sinon toutes), moins les enrichissements si `--no-extras`.

    `--only` nomme une phase explicitement : elle est rendue même si c'est un enrichissement.
    """
    if args.only:
        return [(n, build) for n, build in PHASES if n == args.only]
    if args.from_phase:
        retenues = PHASES[PHASE_NAMES.index(args.from_phase) :]
    else:
        retenues = list(PHASES)
    if args.no_extras:
        retenues = [(n, build) for n, build in retenues if n not in EXTRA_PHASES]
    return retenues


LARGEUR_TITRE_PHASE = 48
"""Largeur du texte dans le cadre d'un titre, la même pour tous."""


def _encadre(lignes: list[str]) -> list[str]:
    """Encadre `lignes`, chacune repliée à la largeur du cadre.

    Un terminal reçoit un cadre de largeur constante, une sortie capturée deux filets horizontaux.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, *lignes, "─" * 40]

    repliees = [repli for ligne in lignes for repli in textwrap.wrap(ligne, LARGEUR_TITRE_PHASE)]
    largeur = LARGEUR_TITRE_PHASE + 4
    return [
        f"╔{'═' * largeur}╗",
        *[f"║  {ligne.ljust(largeur - 2)}║" for ligne in repliees],
        f"╚{'═' * largeur}╝",
    ]


def _champs_fetch_stale(conn: "Connection") -> dict[str, str]:
    from infrastructure.sources.config import get_fetch_stale_after_days

    return {"delai": accord(get_fetch_stale_after_days(conn), "jour")}


_CHAMPS_DE_LIBELLE: dict[str, Callable[["Connection"], dict[str, str]]] = {
    "fetch_stale": _champs_fetch_stale,
}
"""Valeurs des champs de chaque libellé de phase qui en porte, lues en configuration."""


def _libelle_de_phase(name: str) -> str | None:
    """Ce que la phase produit, ses champs remplis par la configuration."""
    # `PHASE_LIBELLES` couvre les phases du pipeline ; les tests en nomment d'autres.
    libelle = PHASE_LIBELLES.get(name)
    champs = _CHAMPS_DE_LIBELLE.get(name)
    if libelle is None or champs is None:
        return libelle
    with open_tx() as conn:
        return libelle.format(**champs(conn))


def _titre_de_phase(name: str, libelle: str | None) -> list[str]:
    """Lignes ouvrant une phase : son nom, et ce qu'elle produit."""
    return _encadre([f"{PHASE_MARKER}{name}", *([libelle] if libelle else [])])


TITRE_PIPELINE = (
    "┏┓ ╻┏┓ ╻  ╻┏━┓┏┳┓┏━╸╺┳╸┏━┓╻┏━╸",
    "┣┻┓┃┣┻┓┃  ┃┃ ┃┃┃┃┣╸  ┃ ┣┳┛┃┣╸",
    "┗━┛╹┗━┛┗━╸╹┗━┛╹ ╹┗━╸ ╹ ╹┗╸╹┗━╸",
)
"""« BIBLIOMETRIE » en caractères de filets, en tête de la bannière d'une exécution."""

_LARGEUR_CLE_REGLAGE = 9
"""Largeur d'une clé de réglage et de ses points de conduite, dans la bannière."""


def _reglage(cle: str, valeur: str) -> list[str]:
    """Lignes « clé ···· valeur » de la bannière, la valeur repliée sous elle-même."""
    tete = f"{cle} {'·' * (_LARGEUR_CLE_REGLAGE - len(cle))} "
    repliee = textwrap.wrap(valeur, LARGEUR_TITRE_PHASE - len(tete)) or [""]
    return [tete + repliee[0], *(" " * len(tete) + suite for suite in repliee[1:])]


def _banniere(reglages: list[str]) -> list[str]:
    """Encadre le titre et les réglages d'une exécution, avec une ombre.

    Un terminal reçoit le cadre, au moins aussi large que celui d'une phase ; une sortie capturée reçoit deux filets et le titre en texte.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, "PIPELINE BIBLIOMÉTRIQUE", *reglages, "─" * 40]

    reglages = [f"  {reglage}" for reglage in reglages]
    largeur_dessin = max(map(len, TITRE_PIPELINE))
    largeur = max(
        LARGEUR_TITRE_PHASE + 4, largeur_dessin + 4, *(len(reglage) + 2 for reglage in reglages)
    )
    # Un même retrait pour toutes les lignes du dessin : centrées une à une, elles se décaleraient.
    retrait = " " * ((largeur - largeur_dessin) // 2)
    corps = ["", *(retrait + ligne for ligne in TITRE_PIPELINE), "", *reglages, ""]
    onglet = "┤ PIPELINE ├"
    return [
        f"┌───{onglet}{'─' * (largeur - 3 - len(onglet))}┐",
        *(f"│{ligne.ljust(largeur)}│▒" for ligne in corps),
        f"└{'─' * largeur}┘▒",
        f" {'▒' * (largeur + 2)}",
    ]


def _titre_du_run(args: argparse.Namespace, phases: list[tuple[str, PhaseBuilder]]) -> list[str]:
    """Lignes ouvrant une exécution : son mode, puis ce qui écarte le lancement du courant."""
    reglages = _reglage("mode", args.mode)

    if args.year:
        reglages += _reglage("année", str(args.year))
    elif args.start_year:
        reglages += _reglage("depuis", str(args.start_year))

    if args.only or args.from_phase:
        reglages += _reglage("phases", ", ".join(n for n, _ in phases))
    elif args.no_extras:
        reglages += _reglage("phases", "sans les enrichissements terminaux")

    options = [
        texte
        for drapeau, texte in (
            (args.rebuild_publications, "publications reconstruites"),
            (args.rebuild_authorships, "signatures reconstruites"),
            (args.rebuild_subjects, "sujets reconstruits"),
            (args.raw_store, "archivage des données brutes"),
            (args.normalize_full, "signatures resynchronisées"),
        )
        if drapeau
    ]
    if options:
        reglages += _reglage("options", ", ".join(options))

    return _banniere(reglages)


def _run_one_phase(
    name: str,
    build: PhaseBuilder,
    *,
    args: argparse.Namespace,
    sources: set[str],
    recorder: PhaseExecutionRecorder,
) -> tuple[str, float]:
    """Construit et exécute une phase, et enregistre son observabilité. Rend son nom et sa durée.

    Une interruption clavier, une `RuntimeError` ou une erreur de base est enregistrée, puis termine le processus ; `--from <phase>` reprend la séquence où elle s'est arrêtée."""
    from sqlalchemy.exc import SQLAlchemyError

    # Injecte le nom de phase dans tous les records émis pendant la phase (logger `normalize:`
    # plutôt que `pipeline:`), y compris depuis les extracteurs threadés qui héritent du contexte.
    phase_token = set_log_phase(name)
    try:
        # Ligne vide devant le cadre : elle le détache de ce que la phase précédente a écrit.
        log.info("")
        for ligne in _titre_de_phase(name, _libelle_de_phase(name)):
            log.info("%s", ligne)
        phase_started_at = datetime.datetime.now(datetime.UTC)
        t0_phase = time.time()
        try:
            result = build().run(
                phase_context(
                    RunOptions(
                        mode=args.mode,
                        sources=sources,
                        year=args.year,
                        start_year=args.start_year,
                        include_wos=args.include_wos,
                        rebuild_publications=args.rebuild_publications,
                        rebuild_authorships=args.rebuild_authorships,
                        rebuild_subjects=args.rebuild_subjects,
                        raw_store=args.raw_store,
                        normalize_full=args.normalize_full,
                    )
                )
            )
        except (KeyboardInterrupt, RuntimeError, SQLAlchemyError) as e:
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
        if isinstance(result, PhaseMetrics):
            # Une phase pose `resume = ""` pour se clore sans un mot, ses barres ayant tout dit.
            if (bilan := result.resume if result.resume is not None else result.as_summary()) != "":
                log.info("")
                log.info("Terminé en %.1fs : %s", duration, bilan)
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
    from infrastructure.observability.phase_executions import start_run

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    # Sources effectivement interrogées : wos est opt-in (`--include-wos`).
    effective_sources = sorted(sources - {"wos"}) if not args.include_wos else sorted(sources)

    # Enregistre le run et chacune de ses phases : identifiant de séquence, entrées, sorties, statut.
    recorder = start_run(mode=args.mode, sources=effective_sources)
    if recorder.run_id is not None:
        log.info("%s%d", RUN_MARKER, recorder.run_id)

    # Matérialise `perimeter_structures` avant toute phase : l'extraction lit le périmètre
    # d'extraction dès la première phase ; `affiliations` la rematérialise ensuite, à son démarrage.
    from infrastructure.pipeline.perimeter import refresh_perimeter_structures

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
    for ligne in _titre_du_run(args, phases_to_run):
        log.info("%s", ligne)
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
