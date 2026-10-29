"""Tests de `domain.publications.contribution_roles` : traduction des rôles des sources, union des rôles d'une contribution."""

from domain.publications.contribution_roles import map_role, merge_roles


class TestMapRole:
    def test_hal_standard(self):
        assert map_role("hal", "aut") == (["author"], False)

    def test_hal_corresponding(self):
        assert map_role("hal", "crp") == (["author"], True)

    def test_wos_author(self):
        assert map_role("wos", "author") == (["author"], False)

    def test_scanr_thesis_director(self):
        assert map_role("scanr", "directeurthese") == (["thesis_director"], False)

    def test_orateur_est_aussi_auteur(self):
        """L'orateur d'une communication en est l'un des auteurs, à sa place dans la liste."""
        assert map_role("hal", "spk") == (["author", "speaker"], False)
        assert map_role("scanr", "presenter") == (["author", "speaker"], False)

    def test_contributeur_est_aussi_auteur(self):
        """Un contributeur HAL ou scanR (`ctb`) figure dans la liste d'auteurs, à sa place ; un conseiller scientifique HAL (`sad`) est seulement contributeur."""
        assert map_role("hal", "ctb") == (["author", "contributor"], False)
        assert map_role("scanr", "ctb") == (["author", "contributor"], False)
        assert map_role("hal", "sad") == (["contributor"], False)

    def test_empty_role_defaults_to_author(self):
        assert map_role("hal", None) == (["author"], False)
        assert map_role("hal", "") == (["author"], False)

    def test_unknown_source_defaults_to_author(self):
        assert map_role("unknown", "aut") == (["author"], False)

    def test_unknown_role_returns_other(self):
        assert map_role("hal", "no_such_role_xyz") == (["other"], False)

    def test_case_insensitive_fallback(self):
        assert map_role("hal", "AUT") == (["author"], False)

    def test_strips_whitespace(self):
        assert map_role("hal", "  aut  ") == (["author"], False)


class TestMergeRoles:
    def test_single_role(self):
        assert merge_roles([["author"]]) == ["author"]

    def test_dedup(self):
        assert merge_roles([["author"], ["author"]]) == ["author"]

    def test_union(self):
        assert merge_roles([["author"], ["editor"]]) == ["author", "editor"]

    def test_sorted_output(self):
        """Le résultat est trié alphabétiquement."""
        result = merge_roles([["editor", "author", "translator"]])
        assert result == sorted(result)

    def test_drops_jury_member_when_specific_role_present(self):
        """Un rôle de jury spécifique (directeur de thèse, rapporteur, président du jury) absorbe `jury_member`."""
        assert "jury_member" not in merge_roles([["thesis_director", "jury_member"]])
        assert "jury_member" not in merge_roles([["rapporteur", "jury_member"]])
        assert "jury_member" not in merge_roles([["jury_president", "jury_member"]])

    def test_keeps_jury_member_alone(self):
        """Sans rôle de jury spécifique, `jury_member` est conservé."""
        assert merge_roles([["jury_member"]]) == ["jury_member"]

    def test_empty(self):
        assert merge_roles([[]]) == []
        assert merge_roles([]) == []
