"""Le graphe des phases est cohérent : noms uniques, tables déclarées."""

from application.pipeline.graph import PHASE_ORDER, PIPELINE_GRAPH, node


def test_phases_uniques():
    assert len(PHASE_ORDER) == len(set(PHASE_ORDER))


def test_node_lookup():
    assert node("normalize").consumes == ("staging",)
    assert "publications" in node("oa_status").consumes


def test_extract_sans_entree_locale():
    extract = node("extract")
    assert extract.consumes == ()
    assert extract.produces == ("staging",)


def test_toutes_les_phases_produisent_une_table():
    for phase in PIPELINE_GRAPH:
        assert phase.produces, f"{phase.name} ne déclare aucune table produite"
