"""Déroulement d'un run : sélection des phases, capture d'observabilité, interruptions.

L'orchestrateur choisit les phases à exécuter, les enchaîne et consigne l'issue de chacune. La trace d'une phase interrompue distingue l'arrêt demandé de l'échec, et indique par où reprendre.

Le câblage des adaptateurs de chaque phase relève du composition root ; le contrôle de types le vérifie.
"""

import argparse
import logging
import sys
from contextlib import nullcontext
from dataclasses import fields
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError, PendingRollbackError

from pipeline import run as run_pipeline
from pipeline.graph import EXTRA_PHASES
from pipeline.runtime.context import RunOptions
from pipeline.runtime.observability.metrics import PhaseMetrics


def _args(**surcharges) -> argparse.Namespace:
    """Renvoie les arguments par défaut de la CLI, sources réduites à HAL, OpenAlex et WoS, puis `surcharges`."""
    base = vars(run_pipeline._build_arg_parser().parse_args([]))
    return argparse.Namespace(**{**base, "sources": "hal,openalex,wos", **surcharges})


def _phase(run):
    """Renvoie la fonction `build` d'une phase de méthode `run(ctx)` égale à `run`."""
    return lambda: SimpleNamespace(run=run)


class _FakeRecorder:
    """Journal d'observabilité : retient ce qui est consigné pour chaque phase."""

    run_id = 7

    def __init__(self) -> None:
        self.records: list[dict] = []
        self.closed = False

    def record(self, **kw) -> None:
        self.records.append(kw)

    def close(self) -> None:
        self.closed = True


class TestSelectPhasesToRun:
    def test_sans_option_toutes_les_phases(self):
        assert run_pipeline._select_phases_to_run(_args()) == list(run_pipeline.PHASES)

    def test_sans_extras_omet_les_enrichissements(self):
        noms = [n for n, _ in run_pipeline._select_phases_to_run(_args(no_extras=True))]

        assert not (set(noms) & EXTRA_PHASES)
        assert noms == [n for n in run_pipeline.PHASE_NAMES if n not in EXTRA_PHASES]

    def test_sans_extras_laisse_passer_une_phase_nommee(self):
        """`--only` prime sur `--no-extras` : l'enrichissement nommé est sélectionné."""
        choisies = run_pipeline._select_phases_to_run(_args(only="subjects", no_extras=True))

        assert [n for n, _ in choisies] == ["subjects"]

    def test_une_seule_phase(self):
        choisies = run_pipeline._select_phases_to_run(_args(only="persons"))

        assert [n for n, _ in choisies] == ["persons"]

    def test_reprise_a_partir_d_une_phase(self):
        """La reprise après incident rejoue la phase nommée et toutes les suivantes."""
        choisies = run_pipeline._select_phases_to_run(_args(from_phase="persons"))
        noms = [n for n, _ in choisies]

        assert noms[0] == "persons"
        assert noms == run_pipeline.PHASE_NAMES[run_pipeline.PHASE_NAMES.index("persons") :]

    @pytest.mark.parametrize("option", ["--only", "--from"])
    def test_phase_inconnue_arrete_le_run(self, option, capsys):
        """Le parseur borne les deux options aux phases connues, et les nomme en refusant."""
        with pytest.raises(SystemExit) as sortie:
            run_pipeline._build_arg_parser().parse_args([option, "inexistante"])

        assert sortie.value.code == 2
        assert "persons" in capsys.readouterr().err

    @pytest.mark.parametrize("valeur", ["", " , ", "hal,inexistante"])
    def test_liste_de_sources_vide_ou_inconnue_arrete_le_run(self, valeur):
        with pytest.raises(SystemExit) as sortie:
            run_pipeline._build_arg_parser().parse_args(["--sources", valeur])

        assert sortie.value.code == 2

    def test_liste_de_sources_normalisee(self):
        args = run_pipeline._build_arg_parser().parse_args(["--sources", " hal , wos "])

        assert args.sources == "hal,wos"


def test_chaque_option_booleenne_arrive_aux_phases():
    """Chaque option booléenne de la CLI renseigne le champ homonyme de `RunOptions`, et chaque champ booléen a son option."""
    flags = {flag.dest for flag in run_pipeline._RUN_FLAGS}
    options = run_pipeline._run_options(_args(**dict.fromkeys(flags, True)), {"hal"})

    assert {f.name for f in fields(RunOptions) if f.type == "bool"} == flags
    assert all(getattr(options, flag) is True for flag in flags)


def _masquant(origine: BaseException) -> PendingRollbackError:
    """Renvoie l'erreur levée par l'annulation d'une transaction sur une connexion perdue ; `origine` est l'exception en cours de traitement."""
    erreur = PendingRollbackError("Can't reconnect until invalid transaction is rolled back")
    erreur.__context__ = origine
    return erreur


class TestRunOnePhase:
    def _executer(self, run, recorder=None, args=None):
        recorder = recorder or _FakeRecorder()
        resultat = run_pipeline._run_one_phase(
            "persons", _phase(run), args=args or _args(), sources={"hal"}, recorder=recorder
        )
        return resultat, recorder

    def test_phase_reussie_consignee(self):
        (nom, duree), recorder = self._executer(lambda ctx: PhaseMetrics(new=3))

        assert nom == "persons"
        assert duree >= 0
        (record,) = recorder.records
        assert record["status"] == "ok"
        assert record["phase"] == "persons"

    def test_phase_porteuse_d_un_signal_consignee_en_avertissement(self):
        metrics = PhaseMetrics()
        metrics.signals.append({"level": "warning", "code": "source_unconfigured", "message": ""})

        _, recorder = self._executer(lambda ctx: metrics)

        assert recorder.records[0]["status"] == "warning"

    def test_une_phase_de_moissonnage_se_clot_sur_son_total(self, caplog):
        with caplog.at_level(logging.INFO):
            run_pipeline._run_one_phase(
                "harvest",
                _phase(lambda ctx: PhaseMetrics(new=2, updated=5, extras={"not_found": 3})),
                args=_args(),
                sources={"hal"},
                recorder=_FakeRecorder(),
            )

        assert caplog.messages[-1] == "Total : 2 nouveaux, 5 mis à jour, 3 introuvables"

    def test_une_autre_phase_ne_donne_pas_de_total(self, caplog):
        with caplog.at_level(logging.INFO):
            self._executer(lambda ctx: PhaseMetrics(new=3))

        assert not any(m.startswith("Total") for m in caplog.messages)

    def test_phase_sans_metriques(self):
        """Une phase sans valeur de retour est consignée avec des compteurs vides."""
        _, recorder = self._executer(lambda ctx: None)

        assert recorder.records[0]["status"] == "ok"

    def test_interruption_utilisateur(self, caplog):
        """L'arrêt demandé est consigné comme un avertissement et dit par où reprendre."""

        def _interrompue(ctx):
            raise KeyboardInterrupt

        with pytest.raises(SystemExit) as sortie, caplog.at_level(logging.INFO):
            self._executer(_interrompue)

        assert sortie.value.code == 130
        assert "run_pipeline --from persons" in caplog.text

    def test_interruption_masquee_par_le_nettoyage(self):
        """Un Ctrl+C en pleine requête invalide la connexion, et le nettoyage lève une erreur SQLAlchemy à la place : la phase se consigne quand même comme interrompue."""

        def _interrompue(ctx):
            raise _masquant(KeyboardInterrupt())

        recorder = _FakeRecorder()
        with pytest.raises(SystemExit) as sortie:
            self._executer(_interrompue, recorder=recorder)

        assert sortie.value.code == 130
        (record,) = recorder.records
        assert record["status"] == "warning"
        assert record["signals"][0]["code"] == "interrupted"

    def test_echec_consigne_avec_son_erreur_d_origine(self):
        """L'erreur levée par le nettoyage masque celle d'origine : le message consigné donne les deux."""

        def _en_echec(ctx):
            raise _masquant(ValueError("colonne inconnue"))

        recorder = _FakeRecorder()
        with pytest.raises(SystemExit) as sortie:
            self._executer(_en_echec, recorder=recorder)

        assert sortie.value.code == 1
        message = recorder.records[0]["signals"][0]["message"]
        assert message.startswith("ValueError : colonne inconnue")
        assert "PendingRollbackError" in message

    def test_echec_de_phase(self, caplog):
        def _en_echec(ctx):
            raise RuntimeError("la source est à bout de budget")

        recorder = _FakeRecorder()
        with pytest.raises(SystemExit) as sortie, caplog.at_level(logging.INFO):
            self._executer(_en_echec, recorder=recorder)

        assert sortie.value.code == 1
        (record,) = recorder.records
        assert record["status"] == "error"
        assert record["signals"][0]["message"] == "la source est à bout de budget"
        assert "run_pipeline --from persons" in caplog.text

    def test_toute_exception_consignee_comme_un_echec(self):
        """Une exception imprévue (erreur HTTP, clé absente…) termine la phase, consignée comme un échec."""

        def _en_echec(ctx):
            raise KeyError("champ")

        recorder = _FakeRecorder()
        with pytest.raises(SystemExit) as sortie:
            self._executer(_en_echec, recorder=recorder)

        assert sortie.value.code == 1
        (record,) = recorder.records
        assert record["status"] == "error"
        assert record["signals"][0]["code"] == "exception"

    def test_perte_de_la_base_consignee_comme_un_echec(self, caplog):
        """Un serveur redémarré coupe les connexions : la phase est consignée comme un échec et le journal dit par où reprendre."""

        def _connexion_perdue(ctx):
            raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))

        recorder = _FakeRecorder()
        with pytest.raises(SystemExit) as sortie, caplog.at_level(logging.INFO):
            self._executer(_connexion_perdue, recorder=recorder)

        assert sortie.value.code == 1
        (record,) = recorder.records
        assert record["status"] == "error"
        assert "run_pipeline --from persons" in caplog.text

    def test_arguments_du_run_transmis_a_la_phase(self):
        recus: dict = {}

        self._executer(
            lambda ctx: recus.update(options=ctx.options) or PhaseMetrics(),
            args=_args(mode="daily", year=2024, include_wos=True),
        )

        options = recus["options"]
        assert options.mode == "daily"
        assert options.year == 2024
        assert options.include_wos is True
        assert options.sources == {"hal"}


class TestExecutePhases:
    @pytest.fixture
    def run_prepare(self, monkeypatch):
        """Neutralise l'ouverture de la base et le journal d'observabilité."""
        recorder = _FakeRecorder()

        def _start_run(**kw):
            recorder.demarrage = kw
            return recorder

        monkeypatch.setattr(run_pipeline, "start_run", _start_run)
        monkeypatch.setattr(run_pipeline, "refresh_perimeter_structures", lambda conn: None)
        monkeypatch.setattr(run_pipeline, "open_tx", nullcontext)
        return recorder

    def test_chaque_phase_consignee_et_journal_clos(self, run_prepare):
        phases = [
            ("une", _phase(lambda ctx: PhaseMetrics())),
            ("deux", _phase(lambda ctx: PhaseMetrics())),
        ]

        run_pipeline._execute_phases(_args(), phases)

        assert [r["phase"] for r in run_prepare.records] == ["une", "deux"]
        assert run_prepare.closed

    def test_wos_ecartee_des_sources_consignees(self, run_prepare):
        """WoS est interrogée seulement sur demande : son crédit d'appels est limité."""
        run_pipeline._execute_phases(_args(sources="hal,wos"), [])

        assert run_prepare.demarrage["sources"] == ["hal"]

    def test_wos_consignee_quand_elle_est_demandee(self, run_prepare):
        run_pipeline._execute_phases(_args(sources="hal,wos", include_wos=True), [])

        assert run_prepare.demarrage["sources"] == ["hal", "wos"]


class TestMain:
    """Point d'entrée : verrou, options d'inspection, et passage à l'exécution."""

    @pytest.fixture
    def lancer(self, monkeypatch):
        """Neutralise le verrou et l'exécution, et retient les phases qui auraient tourné."""
        executees: list[list[str]] = []
        monkeypatch.setattr(run_pipeline, "pipeline_lock", nullcontext)
        monkeypatch.setattr(
            run_pipeline,
            "_execute_phases",
            lambda args, phases: executees.append([n for n, _ in phases]),
        )

        def _lancer(*arguments):
            monkeypatch.setattr(sys, "argv", ["run_pipeline", *arguments])
            run_pipeline.main()
            return executees

        return _lancer

    def test_deroule_toutes_les_phases(self, lancer):
        (executees,) = lancer()

        assert executees == run_pipeline.PHASE_NAMES

    def test_une_seule_phase_demandee(self, lancer):
        (executees,) = lancer("--only", "persons")

        assert executees == ["persons"]

    def test_l_aide_porte_le_catalogue_des_phases(self):
        """L'aide de `--help` nomme chaque phase, suivie de son libellé."""
        catalogue = run_pipeline._catalogue_des_phases()

        for nom in run_pipeline.PHASE_NAMES:
            ligne = next(line for line in catalogue.splitlines() if f" {nom} " in line)
            assert ligne.split(nom, 1)[1].strip()
        assert "Recherche des documents non revus depuis <delai>" in catalogue

    def test_pipeline_deja_en_cours(self, monkeypatch, capsys):
        """Deux pipelines simultanés se bloqueraient en base : le second refuse de démarrer."""

        def _verrou_pris():
            raise run_pipeline.PipelineAlreadyRunningError(
                "Pipeline déjà en cours : run_pipeline@poste (processus 4242)."
            )

        monkeypatch.setattr(run_pipeline, "pipeline_lock", _verrou_pris)
        monkeypatch.setattr(sys, "argv", ["run_pipeline"])

        with pytest.raises(SystemExit) as sortie:
            run_pipeline.main()

        assert sortie.value.code == 1
        assert "déjà en cours" in capsys.readouterr().err

    def test_options_du_run_reconnues(self, monkeypatch):
        """Les options de la ligne de commande arrivent jusqu'à l'exécution."""
        recues: list = []
        monkeypatch.setattr(run_pipeline, "pipeline_lock", nullcontext)
        monkeypatch.setattr(
            run_pipeline, "_execute_phases", lambda args, phases: recues.append(args)
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_pipeline",
                "--mode",
                "daily",
                "--start-year",
                "2020",
                "--sources",
                "hal,openalex",
                "--include-wos",
                "--raw-store",
            ],
        )

        run_pipeline.main()

        (args,) = recues
        assert args.mode == "daily"
        assert args.start_year == 2020
        assert args.sources == "hal,openalex"
        assert args.include_wos is True
        assert args.raw_store is True


def test_arret_demande_par_le_systeme_devient_une_interruption_propre():
    """Un `SIGTERM` (arrêt du conteneur, ordonnanceur) emprunte le même chemin qu'un Ctrl-C : la phase en cours se referme et consigne son interruption."""
    with pytest.raises(KeyboardInterrupt):
        run_pipeline._sigterm_raises_keyboard_interrupt(15, None)
