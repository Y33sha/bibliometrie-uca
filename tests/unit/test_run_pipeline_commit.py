"""Régression : le wrapper de la phase personnes commite avant de fermer la conn.

L'orchestrateur de la phase personnes (`application.pipeline.persons.phase.run`) laisse
« commit/rollback au caller ». Le commit `a6a81f8` (migration SQLAlchemy) avait silencieusement
retiré le `conn.commit()` final, et aucun caller ne reprenait la responsabilité — résultat :
5 semaines de runs `persons` qui matchaient en mémoire puis rollback à la fermeture de connexion.
"""

from unittest.mock import MagicMock, patch


def test_run_persons_phase_commits_before_close():
    fake_conn = MagicMock(name="conn")
    fake_engine = MagicMock(name="engine")
    fake_engine.connect.return_value = fake_conn

    with (
        patch("infrastructure.db.engine.get_sync_engine", return_value=fake_engine),
        patch("application.pipeline.persons.phase.run") as mock_run,
        patch("infrastructure.queries.pipeline.persons_create.PgPersonsCreateQueries"),
        patch("infrastructure.queries.pipeline.name_forms.PgNameFormsQueries"),
        patch("infrastructure.repositories.person_repository"),
        patch("infrastructure.repositories.authorship_repository"),
    ):
        from run_pipeline import _run_persons_phase

        _run_persons_phase()

    mock_run.assert_called_once()
    fake_conn.commit.assert_called_once()
    fake_conn.close.assert_called_once()

    call_order = [c[0] for c in fake_conn.mock_calls if c[0] in ("commit", "close")]
    assert call_order == ["commit", "close"], f"commit doit précéder close, got {call_order}"
