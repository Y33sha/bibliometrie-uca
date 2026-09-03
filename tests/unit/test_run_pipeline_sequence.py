"""Déroulement d'un run : sélection des phases, capture d'observabilité, interruptions.

L'orchestrateur choisit les phases à exécuter, les enchaîne, et consigne l'issue de chacune. Ce qu'il consigne compte autant que ce qu'il exécute : le tableau de bord et la reprise après incident en dépendent. Une phase interrompue doit laisser une trace distinguant l'arrêt demandé par l'utilisatrice de l'échec, et indiquer par où reprendre.

Le câblage des adapters de chaque phase relève du composition root et n'est pas éprouvé ici : il est vérifié par le contrôle de types.
"""

import argparse
import logging
import sys

import pytest

from application.pipeline.metrics import PhaseMetrics
from interfaces.cli import run_pipeline


def _args(**surcharges) -> argparse.Namespace:
    base = {
        "only": None,
        "from_phase": None,
        "mode": "full",
        "sources": "hal,openalex,wos",
        "year": None,
        "start_year": None,
        "include_wos": False,
        "rebuild_publications": False,
        "rebuild_authorships": False,
        "rebuild_subjects": False,
        "no_raw_store": False,
        "dry_run": False,
        "list": False,
        "force": False,
    }
    return argparse.Namespace(**{**base, **surcharges})


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

    def test_une_seule_phase(self):
        choisies = run_pipeline._select_phases_to_run(_args(only="persons"))

        assert [n for n, _ in choisies] == ["persons"]

    def test_reprise_a_partir_d_une_phase(self):
        """La reprise après incident rejoue la phase nommée et toutes les suivantes."""
        choisies = run_pipeline._select_phases_to_run(_args(from_phase="persons"))
        noms = [n for n, _ in choisies]

        assert noms[0] == "persons"
        assert noms == run_pipeline.PHASE_NAMES[run_pipeline.PHASE_NAMES.index("persons") :]

    @pytest.mark.parametrize("option", ["only", "from_phase"])
    def test_phase_inconnue_arrete_le_run(self, option, capsys):
        with pytest.raises(SystemExit) as sortie:
            run_pipeline._select_phases_to_run(_args(**{option: "inexistante"}))

        assert sortie.value.code == 1
        assert "Phase inconnue" in capsys.readouterr().out


class TestRunOnePhase:
    def _executer(self, fn, recorder=None, args=None):
        recorder = recorder or _FakeRecorder()
        resultat = run_pipeline._run_one_phase(
            "persons", fn, args=args or _args(), sources={"hal"}, recorder=recorder
        )
        return resultat, recorder

    def test_phase_reussie_consignee(self):
        (nom, duree), recorder = self._executer(lambda **kw: PhaseMetrics(new=3))

        assert nom == "persons"
        assert duree >= 0
        (record,) = recorder.records
        assert record["status"] == "ok"
        assert record["phase"] == "persons"

    def test_phase_porteuse_d_un_signal_consignee_en_avertissement(self):
        metrics = PhaseMetrics()
        metrics.signals.append({"level": "warning", "code": "source_unconfigured", "message": ""})

        _, recorder = self._executer(lambda **kw: metrics)

        assert recorder.records[0]["status"] == "warning"

    def test_phase_sans_metriques(self):
        """Une phase qui ne rend rien est consignée avec des compteurs vides, non ignorée."""
        _, recorder = self._executer(lambda **kw: None)

        assert recorder.records[0]["status"] == "ok"

    def test_interruption_utilisateur(self, caplog):
        """L'arrêt demandé est un avertissement, non une erreur, et dit par où reprendre."""

        def _interrompue(**kw):
            raise KeyboardInterrupt

        with pytest.raises(SystemExit) as sortie, caplog.at_level(logging.INFO):
            self._executer(_interrompue)

        assert sortie.value.code == 130
        assert "run_pipeline --from persons" in caplog.text

    def test_echec_de_phase(self, caplog):
        def _en_echec(**kw):
            raise RuntimeError("la source est à bout de budget")

        recorder = _FakeRecorder()
        with pytest.raises(SystemExit) as sortie, caplog.at_level(logging.INFO):
            self._executer(_en_echec, recorder=recorder)

        assert sortie.value.code == 1
        (record,) = recorder.records
        assert record["status"] == "error"
        assert record["signals"][0]["message"] == "la source est à bout de budget"
        assert "run_pipeline --from persons" in caplog.text

    def test_arguments_du_run_transmis_a_la_phase(self):
        recus: dict = {}

        self._executer(
            lambda **kw: recus.update(kw) or PhaseMetrics(),
            args=_args(mode="daily", year=2024, include_wos=True),
        )

        assert recus["mode"] == "daily"
        assert recus["year"] == 2024
        assert recus["include_wos"] is True
        assert recus["sources"] == {"hal"}


class TestExecutePhases:
    @pytest.fixture
    def run_prepare(self, monkeypatch):
        """Neutralise l'ouverture de la base et le journal d'observabilité."""
        recorder = _FakeRecorder()
        import infrastructure.observability.phase_executions as observabilite
        import infrastructure.pipeline.perimeter as perimetre

        monkeypatch.setattr(observabilite, "start_run", lambda **kw: recorder)
        monkeypatch.setattr(perimetre, "refresh_perimeter_structures", lambda conn: None)

        from contextlib import contextmanager
        from types import SimpleNamespace

        @contextmanager
        def _connexion():
            yield SimpleNamespace(commit=lambda: None)

        import infrastructure.db.engine as engine_module

        monkeypatch.setattr(
            engine_module, "get_sync_engine", lambda: SimpleNamespace(connect=_connexion)
        )
        return recorder

    def test_chaque_phase_consignee_et_journal_clos(self, run_prepare):
        phases = [("une", lambda **kw: PhaseMetrics()), ("deux", lambda **kw: PhaseMetrics())]

        run_pipeline._execute_phases(_args(), phases)

        assert [r["phase"] for r in run_prepare.records] == ["une", "deux"]
        assert run_prepare.closed

    def test_wos_ecarte_des_sources_annoncees(self, run_prepare, caplog):
        """WoS n'est interrogée que sur demande : son crédit d'appels est limité."""
        with caplog.at_level(logging.INFO):
            run_pipeline._execute_phases(_args(sources="hal,wos"), [])

        assert "Sources : hal" in caplog.text

    def test_wos_annoncee_quand_elle_est_demandee(self, run_prepare, caplog):
        with caplog.at_level(logging.INFO):
            run_pipeline._execute_phases(_args(sources="hal,wos", include_wos=True), [])

        assert "Sources : hal, wos" in caplog.text


class TestMain:
    """Point d'entrée : verrou, options d'inspection, et passage à l'exécution."""

    @pytest.fixture
    def lancer(self, monkeypatch):
        """Neutralise le verrou et l'exécution, et retient les phases qui auraient tourné."""
        executees: list[list[str]] = []
        monkeypatch.setattr(run_pipeline, "acquire_pipeline_lock", lambda *, force: None)
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

    def test_liste_des_phases_sans_rien_lancer(self, lancer, capsys):
        executees = lancer("--list")

        assert executees == []
        assert "persons" in capsys.readouterr().out

    def test_simulation_sans_rien_lancer(self, lancer, capsys):
        executees = lancer("--dry-run")

        assert executees == []
        assert "rien n'a été exécuté" in capsys.readouterr().out

    def test_pipeline_deja_en_cours(self, monkeypatch, capsys):
        """Deux pipelines simultanés se bloqueraient en base : le second refuse de démarrer."""

        def _verrou_pris(*, force):
            raise run_pipeline.PipelineAlreadyRunningError("Pipeline déjà en cours (PID 4242).")

        monkeypatch.setattr(run_pipeline, "acquire_pipeline_lock", _verrou_pris)
        monkeypatch.setattr(sys, "argv", ["run_pipeline"])

        with pytest.raises(SystemExit) as sortie:
            run_pipeline.main()

        assert sortie.value.code == 1
        assert "déjà en cours" in capsys.readouterr().err

    def test_options_du_run_reconnues(self, monkeypatch):
        """Les options de la ligne de commande arrivent bien jusqu'à l'exécution."""
        recues: list = []
        monkeypatch.setattr(run_pipeline, "acquire_pipeline_lock", lambda *, force: None)
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
                "--no-raw-store",
            ],
        )

        run_pipeline.main()

        (args,) = recues
        assert args.mode == "daily"
        assert args.start_year == 2020
        assert args.sources == "hal,openalex"
        assert args.include_wos is True
        assert args.no_raw_store is True


def test_arret_demande_par_le_systeme_devient_une_interruption_propre():
    """Un `SIGTERM` (arrêt du conteneur, ordonnanceur) emprunte le même chemin qu'un Ctrl-C : la phase en cours se referme et consigne son interruption."""
    with pytest.raises(KeyboardInterrupt):
        run_pipeline._sigterm_raises_keyboard_interrupt(15, None)
