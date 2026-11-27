"""Page du déroulement du pipeline : chaque tâche rangée une fois et décrite, page de la documentation à jour."""

from interfaces.cli.dev.deroulement.page import DOC_PAGE, document, problems


def test_chaque_tache_est_rangee_une_fois_et_decrite():
    assert problems() == []


def test_la_page_de_la_documentation_est_a_jour():
    assert DOC_PAGE.read_text() == document(), "uv run python -m interfaces.cli.dev.deroulement"
