"""Nature d'une monographie (`domain.monographs.proceedings`)."""

from domain.monographs.proceedings import MonographRecord, is_proceedings_volume

CHAPTER = MonographRecord("crossref", "book-chapter", False)


def test_enregistrement_issu_d_un_congres():
    records = [CHAPTER, MonographRecord("crossref", "proceedings-article", False)]
    assert is_proceedings_volume(records, collection_type=None, title="Metaheuristics")


def test_congres_declare_par_crossref():
    records = [MonographRecord("crossref", "book-chapter", True)]
    assert is_proceedings_volume(records, collection_type=None, title="Metaheuristics")


def test_collection_d_actes():
    """Cas réel : un volume LNCS dont les chapitres Crossref ne déclarent pas le congrès."""
    assert is_proceedings_volume(
        [CHAPTER], collection_type="proceedings", title="Fun with Algorithms"
    )


def test_titre_anglais_d_actes():
    title = "Proceedings of the Thirtieth Annual ACM-SIAM Symposium on Discrete Algorithms"
    assert is_proceedings_volume([CHAPTER], collection_type=None, title=title)


def test_actes_de_colloque_en_sciences_humaines_restent_un_livre():
    title = "Aux confins du droit administratif. Actes du colloque de Lyon du 16 septembre 2022"
    assert not is_proceedings_volume(
        [MonographRecord("hal", "COUV", False)], collection_type=None, title=title
    )


def test_livre():
    assert not is_proceedings_volume(
        [CHAPTER], collection_type="book_series", title="Third Parties in Criminal Proceedings"
    )
