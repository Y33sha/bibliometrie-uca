"""Choix des exemples du script de captures d'écran du guide utilisateur."""

from interfaces.cli.dev.screenshots import SAMPLES, SHOTS, Shot, matches_sample, sample_keys


def test_only_samples_used_by_selected_shots_are_resolved():
    shots = [Shot("structures", "structures"), Shot("journal_dashboard", "journals/{serial}")]
    assert sample_keys(shots) == {"serial"}


def test_every_shot_placeholder_is_a_known_sample():
    assert sample_keys(SHOTS) <= SAMPLES.keys()


def test_list_field_matches_when_it_contains_the_value():
    assert matches_sample(["0000-0001", "1029-8479"], "1029-8479")
    assert not matches_sample(["0000-0001"], "1029-8479")


def test_scalar_field_matches_on_equality():
    assert matches_sample("LMV", "LMV")
    assert not matches_sample("LMV2", "LMV")
