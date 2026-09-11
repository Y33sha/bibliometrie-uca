"""Libellés des facettes APC des statistiques : ils portent le nom de l'établissement servi."""

from types import SimpleNamespace

from infrastructure.read_models.stats.summary import _build_facets_result


def test_apc_labels_carry_institution_name():
    apc_row = SimpleNamespace(apc_uca=3, apc_non_uca=2, apc_none=1)

    result = _build_facets_result([], [], [], apc_row, [], institution="UL")

    assert [option.label for option in result.apc] == ["APC UL", "APC hors UL", "Sans APC"]
