"""Tests du calcul des formes de nom d'une personne."""

from domain.persons.name_forms import compute_person_name_forms, contributor_name_forms


class TestComputePersonNameForms:
    def test_prenom_nom_et_initiales_nom(self) -> None:
        assert compute_person_name_forms("Dupont", "Jean Michel") == {
            "jean michel dupont",
            "j m dupont",
        }

    def test_prenom_en_initiales_collees(self) -> None:
        """Prénom normalisé comme celui des contributions sources : « JP » donne « j p »."""
        assert compute_person_name_forms("Dupont", "JP") == {"j p dupont"}

    def test_accents(self) -> None:
        assert compute_person_name_forms("Bensoussan", "Népomucène") == {
            "nepomucene bensoussan",
            "n bensoussan",
        }

    def test_annee_de_naissance_retiree(self) -> None:
        """Le prénom d'une personne créée d'après une forme d'autorité contient l'année de naissance ; ses formes de nom l'omettent."""
        assert compute_person_name_forms("Chométy", "Philippe 1973-") == {
            "philippe chomety",
            "p chomety",
        }

    def test_sans_prenom(self) -> None:
        assert compute_person_name_forms("Dupont", "") == {"dupont"}

    def test_sans_nom(self) -> None:
        assert compute_person_name_forms("", "Jean") == set()


class TestContributorNameForms:
    def test_prenom_nom_puis_nom_prenom(self) -> None:
        assert contributor_name_forms("dupont", "marie") == ("marie dupont", "dupont marie")

    def test_sans_prenom(self) -> None:
        assert contributor_name_forms("dupont", None) == ("dupont",)
