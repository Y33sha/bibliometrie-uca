"""Facettes APC des statistiques : libellés au nom de l'établissement servi, valeurs `yes` / `no` du filtre."""

from types import SimpleNamespace

from infrastructure.read_models.stats.summary import _build_facets_result
from interfaces.api.filters import TOGGLE_VALUES

_APC_ROW = SimpleNamespace(apc_yes=3, apc_no=2)


def test_apc_labels_carry_institution_name():
    result = _build_facets_result([], [], [], _APC_ROW, [], institution="UL")

    assert [option.label for option in result.apc] == ["APC UL", "Sans APC"]


def test_apc_values_belong_to_filter_vocabulary():
    result = _build_facets_result([], [], [], _APC_ROW, [], institution="UL")

    assert {option.value for option in result.apc} == TOGGLE_VALUES
