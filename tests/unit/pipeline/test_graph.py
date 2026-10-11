"""Le graphe de dépendances du pipeline (`pipeline.graph`) est cohérent avec l'ordre d'exécution."""

from pipeline.graph import NODES, Node, order_violations
from pipeline.phase_order import PHASE_ORDER


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
