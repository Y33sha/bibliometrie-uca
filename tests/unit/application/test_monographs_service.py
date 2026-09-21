"""Tests du trouve-ou-crée des monographies (`application.services.monographs.core`)."""

from application.ports.pipeline.monographs import MonographMatch
from application.services.monographs.core import find_or_create_monograph

# ISBN valides : Springer (papier et électronique), ISBN-10 converti.
_PAPER = "9783030580803"
_ELECTRONIC = "9783030580810"
_OTHER_VOLUME = "9782410013221"


class _Repo:
    def __init__(self) -> None:
        self.rows: dict[int, dict] = {}

    def find_monograph_by_isbn(self, isbn: str) -> int | None:
        return next((mid for mid, r in self.rows.items() if isbn in (r["isbn"], r["eisbn"])), None)

    def find_monographs_by_title(self, title_normalized, publisher_id):
        return [
            MonographMatch(mid, r["isbn"], r["eisbn"])
            for mid, r in self.rows.items()
            if r["title_normalized"] == title_normalized and r["publisher_id"] == publisher_id
        ]

    def create_monograph(self, **fields) -> int:
        mid = len(self.rows) + 1
        self.rows[mid] = fields
        return mid

    def enrich_monograph(self, monograph_id, **fields) -> None:
        row = self.rows[monograph_id]
        row["proceedings"] = row["proceedings"] or fields["proceedings"]
        for key in ("year", "isbn", "eisbn", "publisher_id", "journal_id"):
            row[key] = row[key] if row[key] is not None else fields[key]


def _find(repo, title, **kwargs):
    kwargs.setdefault("proceedings", False)
    return find_or_create_monograph(title, repo=repo, **kwargs)


def test_isbn_reunit_deux_titres_differents():
    repo = _Repo()
    first = _find(repo, "Green polymers filaments", isbns=[_PAPER], publisher_id=1)
    second = _find(repo, "Green polymer filaments", eisbns=[_PAPER], publisher_id=2)
    assert first == second
    assert len(repo.rows) == 1


def test_titre_et_editeur_reunissent_sans_isbn():
    repo = _Repo()
    first = _find(repo, "Le Paris du Moyen Âge", publisher_id=1)
    second = _find(repo, "Le Paris du moyen age", publisher_id=1)
    assert first == second


def test_meme_titre_chez_deux_editeurs_donne_deux_monographies():
    repo = _Repo()
    assert _find(repo, "Introduction", publisher_id=1) != _find(
        repo, "Introduction", publisher_id=2
    )


def test_isbn_arrive_sur_une_monographie_creee_par_son_titre():
    repo = _Repo()
    mid = _find(repo, "Le Paris du Moyen Âge", publisher_id=1)
    assert _find(repo, "Le Paris du Moyen Âge", isbns=[_PAPER], publisher_id=1) == mid
    assert repo.rows[mid]["isbn"] == _PAPER


def test_volumes_de_meme_titre_restent_distincts():
    repo = _Repo()
    first = _find(repo, "Handbook", isbns=[_PAPER], publisher_id=1)
    second = _find(repo, "Handbook", isbns=[_OTHER_VOLUME], publisher_id=1)
    assert first != second
    # Sans ISBN, rien ne départage les volumes : aucun rattachement.
    assert _find(repo, "Handbook", publisher_id=1) is None


def test_isbn_ranges_par_support_isbn_10_converti():
    repo = _Repo()
    mid = _find(repo, "Book", isbns=["3-030-58080-6"], eisbns=[_ELECTRONIC], publisher_id=1)
    assert (repo.rows[mid]["isbn"], repo.rows[mid]["eisbn"]) == (_PAPER, _ELECTRONIC)


def test_un_article_de_congres_fait_d_un_livre_un_volume_d_actes():
    repo = _Repo()
    mid = _find(repo, "Proceedings of X", isbns=[_PAPER])
    _find(repo, "Proceedings of X", isbns=[_PAPER], proceedings=True)
    assert repo.rows[mid]["proceedings"] is True


def test_sans_titre_ni_isbn_aucune_monographie():
    assert _find(_Repo(), None) is None
