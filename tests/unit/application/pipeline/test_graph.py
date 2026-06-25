"""Le graphe des phases est un DAG cohérent et en ordre topologique."""

from application.pipeline.graph import PHASE_ORDER, PIPELINE_GRAPH, node


def test_phases_uniques():
    assert len(PHASE_ORDER) == len(set(PHASE_ORDER))


def test_amonts_existent_et_precedent():
    seen: set[str] = set()
    for phase in PIPELINE_GRAPH:
        for parent in phase.upstream:
            assert parent in PHASE_ORDER, f"{phase.name} : amont inconnu {parent}"
            assert parent in seen, f"{phase.name} : amont {parent} non topologique"
        seen.add(phase.name)


def test_node_lookup():
    assert node("normalize").upstream == ("refetch_truncated",)
    assert "publications" in node("authorships").upstream


def test_extract_sans_amont_et_sans_entree():
    extract = node("extract")
    assert extract.upstream == ()
    assert extract.consumes == ()
    assert extract.produces == ("staging",)
