"""Facettes APC des statistiques : libellés au nom de l'établissement servi, valeurs du vocabulaire du filtre."""

from types import SimpleNamespace

from application.ports.read_models.publications_queries import APC_ORIGINS
from infrastructure.read_models.stats.summary import _build_facets_result

_APC_ROW = SimpleNamespace(apc_institution=3, apc_other=2, apc_none=1)


def test_apc_labels_carry_institution_name():
    result = _build_facets_result([], [], [], _APC_ROW, [], institution="UL")

    assert [option.label for option in result.apc] == ["APC UL", "APC hors UL", "Sans APC"]


def test_apc_values_belong_to_filter_vocabulary():
    result = _build_facets_result([], [], [], _APC_ROW, [], institution="UL")

    assert {option.value for option in result.apc} == APC_ORIGINS
