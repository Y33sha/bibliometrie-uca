"""Le graphe des phases est cohérent : noms uniques, tables déclarées."""

from application.pipeline.graph import PHASE_ORDER, PIPELINE_GRAPH, node, watched_tables


def test_phases_uniques():
    assert len(PHASE_ORDER) == len(set(PHASE_ORDER))


def test_watched_tables_union_sans_doublon():
    # `affiliations` consomme source_authorships et produit source_authorships + addresses :
    # l'union dédupliquée préserve l'ordre et ne répète pas source_authorships.
    assert watched_tables("affiliations") == ("source_authorships", "addresses")
    assert watched_tables("extract") == ("staging",)


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
