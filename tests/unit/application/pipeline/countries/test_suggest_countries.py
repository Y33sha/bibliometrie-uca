"""Suggestion de pays : l'automate Aho-Corasick inversé, et la passe qui l'alimente.

`CountrySuggester` porte la règle de rapprochement ; `run` porte le parcours — pool chargé une fois, cibles paginées par keyset, commit par lot — et le choix des adresses à traiter, que `retry_empty` élargit aux tentatives restées sans résultat.
"""

import logging

from application.pipeline.countries.suggest_countries import CountrySuggester, run
from application.ports.pipeline.countries import SuggestEligibleCounts

_LOG = logging.getLogger("test")


class TestCountrySuggester:
    def test_picks_majority_country(self):
        targets = [(1, "lab foo")]
        pool = [
            ("lab foo univ a", ["FR"]),
            ("lab foo univ b", ["FR"]),
            ("lab foo univ c", ["FR"]),
            ("lab foo univ d", ["US"]),
        ]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR"]}

    def test_returns_all_tied_sorted(self):
        targets = [(1, "foo bar")]
        pool = [("foo bar a", ["FR"]), ("foo bar b", ["US"]), ("foo bar c", ["DE"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["DE", "FR", "US"]}

    def test_no_match_absent_from_result(self):
        targets = [(1, "truc inconnu")]
        pool = [("lab foo univ a", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {}

    def test_substring_not_just_prefix(self):
        # La cible peut être au milieu d'une adresse pool, pas seulement préfixe.
        targets = [(1, "clermont ferrand")]
        pool = [("univ x clermont ferrand cedex france", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR"]}

    def test_target_matches_whole_words_only(self):
        # Match au mot près : « ip » se distingue de « philippe » et « equipe ».
        targets = [(1, "ip")]
        pool = [("philippe equipe lab", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {}

    def test_short_target_matches_as_whole_word(self):
        # Une cible courte reste éligible dès lors qu'elle matche un mot entier.
        targets = [(1, "ip")]
        pool = [("lab ip univ", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR"]}

    def test_target_matches_at_pool_text_boundaries(self):
        # Le texte du pool est encadré d'espaces : une cible en tête ou en queue matche.
        targets = [(1, "lyon")]
        pool = [("lyon cedex", ["FR"]), ("chu de lyon", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR"]}

    def test_pool_address_counts_once_per_target(self):
        # "ab" apparaît 2x dans la 1re adresse pool mais ne compte qu'une fois.
        targets = [(1, "ab")]
        pool = [("ab xx ab", ["FR"]), ("ab", ["US"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR", "US"]}

    def test_multiple_targets_same_normalized_text(self):
        # Deux adresses cibles partageant le même normalized_text.
        targets = [(1, "lab foo"), (2, "lab foo")]
        pool = [("lab foo univ", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR"], 2: ["FR"]}

    def test_country_codes_trimmed(self):
        # char(2) peut arriver avec un espace de remplissage ; les codes sont strippés.
        targets = [(1, "lab foo")]
        pool = [("lab foo univ", ["fr "])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["fr"]}

    def test_pool_address_without_country_ignored(self):
        targets = [(1, "lab foo")]
        pool = [("lab foo univ a", None), ("lab foo univ b", []), ("lab foo univ c", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR"]}

    def test_target_without_normalized_text_ignored(self):
        # Une adresse dont le texte normalisé est vide n'a rien à quoi se rapprocher.
        targets = [(1, ""), (2, "lab foo")]
        pool = [("lab foo univ", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {2: ["FR"]}

    def test_empty_targets(self):
        assert CountrySuggester([]).suggest([("lab foo", ["FR"])]) == {}

    def test_multi_country_pool_address(self):
        # Une adresse pool multi-pays crédite chacun de ses pays à la cible.
        targets = [(1, "lab foo")]
        pool = [("lab foo univ", ["FR", "BE"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["BE", "FR"]}

    def test_pool_address_with_blank_countries_ignored(self):
        # Des codes réduits à des espaces ne valent pas un pays.
        targets = [(1, "lab foo")]
        pool = [("lab foo univ a", ["  ", ""]), ("lab foo univ b", ["FR"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["FR"]}


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakeCountryQueries:
    """Doublure du port : rend les tranches de cibles posées à la construction, puis plus rien.

    Les écritures sont retenues telles quelles, avec la colonne visée.
    """

    def __init__(self, *, tranches=(), pool=(), counts=None):
        self._tranches = list(tranches)
        self._pool = list(pool)
        self._counts = counts or SuggestEligibleCounts(
            eligible=sum(len(t) for t in tranches), has_suggestion=0, empty_attempted=0
        )
        self.ecritures: list[tuple[list, str]] = []
        self.pool_charge = 0
        self.retry_demande: list[bool] = []
        self.apres_id: list[int] = []

    def count_suggest_eligible(self, conn) -> SuggestEligibleCounts:
        return self._counts

    def load_country_pool(self, conn) -> list:
        self.pool_charge += 1
        return self._pool

    def fetch_suggest_targets_chunk(self, conn, *, after_id, limit, retry_empty=False) -> list:
        self.retry_demande.append(retry_empty)
        self.apres_id.append(after_id)
        return self._tranches.pop(0) if self._tranches else []

    def write_countries(self, conn, rows, *, target_column="suggested_countries") -> None:
        self.ecritures.append((rows, target_column))


class TestRun:
    def test_rien_a_traiter(self):
        queries = _FakeCountryQueries(
            counts=SuggestEligibleCounts(eligible=0, has_suggestion=12, empty_attempted=3)
        )

        metrics = run(_FakeConnection(), queries, _LOG)

        assert (metrics.seen, metrics.new) == (0, 0)
        assert queries.pool_charge == 0  # le pool coûte cher : il n'est pas chargé pour rien

    def test_parcourt_les_tranches_et_commite_chacune(self):
        queries = _FakeCountryQueries(
            tranches=[[(1, "lab foo"), (2, "truc inconnu")], [(7, "lab foo")]],
            pool=[("lab foo univ", ["FR"])],
        )
        conn = _FakeConnection()

        metrics = run(conn, queries, _LOG, batch_size=2)

        assert (metrics.seen, metrics.new) == (3, 2)
        assert conn.commits == 2
        assert queries.pool_charge == 1  # chargé une fois, rescanné à chaque tranche
        assert queries.apres_id == [0, 2, 7]  # pagination par le dernier identifiant de la tranche

    def test_ecrit_un_tableau_vide_pour_une_cible_sans_correspondance(self):
        queries = _FakeCountryQueries(
            tranches=[[(1, "lab foo"), (2, "truc inconnu")]],
            pool=[("lab foo univ", ["FR"])],
        )

        run(_FakeConnection(), queries, _LOG)

        rows, colonne = queries.ecritures[0]
        assert rows == [(1, ["FR"]), (2, [])]
        assert colonne == "suggested_countries"

    def test_retry_empty_elargit_le_compte_et_la_demande(self):
        queries = _FakeCountryQueries(
            tranches=[[(1, "lab foo")]],
            pool=[("lab foo univ", ["FR"])],
            counts=SuggestEligibleCounts(eligible=1, has_suggestion=0, empty_attempted=5),
        )

        metrics = run(_FakeConnection(), queries, _LOG, retry_empty=True)

        assert metrics.seen == 1
        assert all(queries.retry_demande)  # les tentatives sans résultat sont rejointes
