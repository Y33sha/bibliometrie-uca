"""Tests de la séparation d'un conteneur en série et volume (`determine_container_type`)."""

from domain.journals.containers import ContainerDescription, determine_container_type


def _describe(**fields) -> ContainerDescription:
    fields.setdefault("source", "crossref")
    fields.setdefault("raw_doc_type", "book-chapter")
    return ContainerDescription(**fields)


def test_article_sa_revue_pour_serie():
    series, volume = determine_container_type(
        _describe(raw_doc_type="journal-article", journal_title="J. Things", issn="1234-5678")
    )
    assert (series.title, series.issn) == ("J. Things", "1234-5678")
    assert volume is None


def test_article_dans_une_edition_datee_de_congres_sans_issn():
    """Cas réel : OpenAlex classe en article une communication dont la source est le congrès daté."""
    series, volume = determine_container_type(
        _describe(
            raw_doc_type="article", source="openalex", journal_title="2021 21st ICCAS", year=2021
        )
    )
    assert series is None
    assert (volume.title, volume.proceedings, volume.year) == ("2021 21st ICCAS", True, 2021)


def test_revue_datee_avec_issn_reste_une_serie():
    series, volume = determine_container_type(
        _describe(
            raw_doc_type="journal-article", journal_title="Periodontology 2000", issn="0906-6713"
        )
    )
    assert series.title == "Periodontology 2000"
    assert volume is None


def test_article_sans_conteneur():
    assert determine_container_type(_describe(raw_doc_type="journal-article")) == (None, None)


def test_chapitre_livre_et_collection():
    """Cas réel : chapitre d'un livre de la collection IFIP AICT."""
    series, volume = determine_container_type(
        _describe(
            collection_title="IFIP Advances in Information and Communication Technology",
            book_title="Advances in Production Management Systems",
            issn="1868-4238",
            isbns=("9783030580803",),
        )
    )
    assert series.title == "IFIP Advances in Information and Communication Technology"
    assert (volume.title, volume.isbns, volume.proceedings) == (
        "Advances in Production Management Systems",
        ("9783030580803",),
        False,
    )


def test_chapitre_sans_issn_sans_serie():
    series, volume = determine_container_type(_describe(book_title="Le Paris du Moyen Âge"))
    assert series is None
    assert volume.title == "Le Paris du Moyen Âge"


def test_livre_porte_son_propre_titre():
    _, volume = determine_container_type(
        _describe(raw_doc_type="book", document_title="Global Handbook of Health")
    )
    assert volume.title == "Global Handbook of Health"


def test_volume_qui_porte_l_issn_de_sa_collection():
    """Cas réel : HAL nomme le volume ICORES 2023 et donne l'ISSN de la série ICORES."""
    title = (
        "Proceedings of the 12th International Conference on Operations Research"
        " and Enterprise Systems (ICORES 2023)"
    )
    series, volume = determine_container_type(
        _describe(source="hal", raw_doc_type="COMM", collection_title=title, issn="2184-4372")
    )
    assert series.title == (
        "Proceedings of the International Conference on Operations Research"
        " and Enterprise Systems (ICORES)"
    )
    assert (volume.title, volume.proceedings) == (title, True)


def test_communication_parue_dans_une_revue_sans_volume():
    """Cas réel : WoS type « Article; Proceedings Paper » un article de revue issu d'un congrès."""
    series, volume = determine_container_type(
        _describe(
            source="wos",
            raw_doc_type="Article; Proceedings Paper",
            collection_title="Physical Review D",
            book_title="Physical Review D",
            issn="2470-0010",
        )
    )
    assert series.title == "Physical Review D"
    assert volume is None


def test_chapitre_sans_titre_de_livre_retrouve_par_son_isbn():
    """Cas réel : chapitre Classiques Garnier, dont seul l'ISBN du livre est connu."""
    _, volume = determine_container_type(
        _describe(source="datacite", raw_doc_type="BookChapter", isbns=("9782406142003",))
    )
    assert (volume.title, volume.isbns) == (None, ("9782406142003",))


def test_chapitre_sans_titre_ni_isbn_sans_volume():
    assert determine_container_type(_describe(issn="1868-4238"))[1] is None
