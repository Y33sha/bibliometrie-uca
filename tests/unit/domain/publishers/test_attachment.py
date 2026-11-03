"""`attach_publishers` : rattachement en lot des enregistrements sources à leur éditeur."""

from itertools import permutations

from domain.publishers.attachment import NewPublisher, PublisherRecord, attach_publishers


def test_l_identifiant_openalex_connu_designe_l_editeur():
    result = attach_publishers([PublisherRecord(1, "Elsevier BV", "P1")], {"P1": 10}, {})
    assert result.publisher_of == {1: 10}
    assert result.new_forms == {"elsevier": 10}


def test_la_forme_de_nom_designe_l_editeur_sans_identifiant_openalex():
    result = attach_publishers([PublisherRecord(1, "Elsevier", None)], {}, {"elsevier": 10})
    assert result.publisher_of == {1: 10}
    assert result.new_forms == {}


def test_une_forme_libre_cree_un_editeur():
    records = [PublisherRecord(1, "Zeta Press", None), PublisherRecord(2, "ZETA PRESS", None)]
    result = attach_publishers(records, {}, {})
    created = NewPublisher("form:zeta press", "ZETA PRESS")
    assert result.publisher_of == {1: created, 2: created}
    assert result.new_forms == {"zeta press": created}


def test_un_identifiant_openalex_inconnu_rejoint_l_editeur_de_sa_forme_et_lui_est_attribue():
    result = attach_publishers([PublisherRecord(1, "Elsevier", "P1")], {}, {"elsevier": 10})
    assert result.publisher_of == {1: 10}
    assert result.openalex_ids == {10: "P1"}


def test_un_editeur_qui_a_deja_un_identifiant_openalex_le_garde():
    result = attach_publishers([PublisherRecord(1, "Elsevier", "P2")], {"P1": 10}, {"elsevier": 10})
    assert result.publisher_of == {1: 10}
    assert result.openalex_ids == {}


def test_un_identifiant_openalex_sans_forme_connue_cree_un_editeur():
    result = attach_publishers([PublisherRecord(1, "Wiley", "P1")], {}, {})
    created = NewPublisher("openalex:P1", "Wiley", "P1")
    assert result.publisher_of == {1: created}
    assert result.new_forms == {"wiley": created}


def test_le_rattachement_est_independant_de_l_ordre():
    """Exemple de l'inventaire : un éditeur trouvé par son identifiant OpenAlex sous un nom aussi donné par une autre source."""
    records = [
        PublisherRecord(1, "Elsevier", "P1"),
        PublisherRecord(2, "Elsevier Masson", "P1"),
        PublisherRecord(3, "Elsevier Masson", None),
    ]
    results = [
        attach_publishers(order, {"P1": 10}, {"elsevier": 10}) for order in permutations(records)
    ]
    assert all(r.publisher_of == {1: 10, 2: 10, 3: 10} for r in results)
    assert all(r.new_forms == {"elsevier masson": 10} for r in results)


def test_une_forme_libre_va_a_l_identifiant_qui_la_porte_le_plus():
    records = [
        PublisherRecord(1, "Masson", "P1"),
        PublisherRecord(2, "Masson", "P2"),
        PublisherRecord(3, "Masson", "P2"),
    ]
    result = attach_publishers(records, {"P1": 10, "P2": 11}, {})
    assert result.new_forms == {"masson": 11}


def test_un_nom_sans_forme_reste_sans_editeur():
    assert attach_publishers([PublisherRecord(1, "Ltd", None)], {}, {}).publisher_of == {}
