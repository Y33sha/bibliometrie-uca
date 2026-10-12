"""Le graphe de dépendances du pipeline (`pipeline.graph`) est cohérent avec l'ordre d'exécution."""

from domain.sources.registry import (
    ALL_SOURCES,
    DOI_SEARCHABLE_SOURCES,
    HARVESTED_SOURCES,
    SOURCE_PRIORITY,
)
from pipeline.graph import NODES, Node, order_violations
from pipeline.ingestion.common import extract
from pipeline.ingestion.common.normalize import _normalize_builders
from pipeline.runtime.phase_order import PHASE_ORDER


def test_noms_uniques():
    names = [n.name for n in NODES]
    assert len(names) == len(set(names))


def test_groupes_dans_l_ordre_des_phases():
    """Les nœuds sont déclarés dans l'ordre d'exécution : le périmètre matérialisé, puis les phases dans leur ordre."""
    groups = list(dict.fromkeys(n.group for n in NODES))
    assert groups == ["run", *PHASE_ORDER]
    assert [n.group for n in NODES] == sorted(
        (n.group for n in NODES), key=["run", *PHASE_ORDER].index
    )


def test_un_noeud_d_extraction_par_source_moissonnee():
    extract_nodes = [n.name for n in NODES if n.group == "extract"]
    assert extract_nodes == [f"extract.{s}" for s in HARVESTED_SOURCES]
    assert set(extract._extractors()) == {s.value for s in HARVESTED_SOURCES}


def test_un_noeud_de_relecture_par_source():
    """Crossref aussi : `fetch_stale` relit toutes les sources par identifiant natif."""
    stale_nodes = [n.name for n in NODES if n.group == "fetch_stale"]
    assert stale_nodes == [f"fetch_stale.{s}" for s in ALL_SOURCES]


def test_un_noeud_de_recherche_par_doi_par_source_interrogeable():
    """HAL aussi : `fetch_missing` l'interroge par DOI, en plus des canaux hal-id et NNT."""
    doi_nodes = [n.name for n in NODES if n.name.startswith("fetch_missing.doi.")]
    assert doi_nodes == [f"fetch_missing.doi.{s}" for s in DOI_SEARCHABLE_SOURCES]


def test_normalisation_dans_l_ordre_de_priorite_des_sources():
    normalize_nodes = [
        n.name.removeprefix("normalize.")
        for n in NODES
        if n.group == "normalize" and n.name.removeprefix("normalize.") in set(SOURCE_PRIORITY)
    ]
    assert normalize_nodes == [s.value for s in SOURCE_PRIORITY]
    assert set(_normalize_builders(archive=False)) == {s.value for s in SOURCE_PRIORITY}


def test_aucun_noeud_ne_lit_une_donnee_ecrite_apres_lui():
    """Toute lecture d'une donnée qu'un nœud placé après écrit est déclarée lue au run précédent."""
    assert order_violations(NODES) == []


def test_lecture_non_declaree_detectee():
    writer = Node("b", "g", writes=frozenset({"t.c"}))
    reader = Node("a", "g", reads=frozenset({"t"}))
    assert order_violations([reader, writer]) == [("a", "t", "b")]
    declared = Node("a", "g", reads=frozenset({"t"}), previous_run=frozenset({"t.c"}))
    assert order_violations([declared, writer]) == []


def test_creation_de_lignes_change_toute_lecture_de_la_table():
    writer = Node("b", "g", writes=frozenset({"t.id"}))
    reader = Node("a", "g", reads=frozenset({"t.c"}))
    assert order_violations([reader, writer]) == [("a", "t.c", "b")]
    column_writer = Node("b", "g", writes=frozenset({"t.c"}))
    id_reader = Node("a", "g", reads=frozenset({"t.id"}))
    assert order_violations([id_reader, column_writer]) == []
