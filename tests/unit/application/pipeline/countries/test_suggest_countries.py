"""Tests unitaires de `CountrySuggester` (automate Aho-Corasick inversé)."""

from application.pipeline.countries.suggest_countries import CountrySuggester


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

    def test_empty_targets(self):
        assert CountrySuggester([]).suggest([("lab foo", ["FR"])]) == {}

    def test_multi_country_pool_address(self):
        # Une adresse pool multi-pays crédite chacun de ses pays à la cible.
        targets = [(1, "lab foo")]
        pool = [("lab foo univ", ["FR", "BE"])]
        assert CountrySuggester(targets).suggest(pool) == {1: ["BE", "FR"]}
