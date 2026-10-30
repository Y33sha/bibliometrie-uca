"""Tests de l'écriture partagée des contributions sources : neutralisation des identifiants partagés dans un enregistrement source, colonnes de nom, texte des adresses."""

from domain.persons.contributor_name import ContributorName
from pipeline.ingestion.common.source_contributions import (
    AddressRecord,
    AuthorRecord,
    contributor_name_fields,
    write_source_contributions,
)
from tests.helpers.normalize_doubles import FakeSourceContributionStore


def _items_written(records: list[AuthorRecord]) -> list[dict]:
    queries = FakeSourceContributionStore()
    write_source_contributions(queries, "crossref", 1, records)
    return queries.upserted_batches[0]


def _record(position: int, raw: str, orcid: str) -> AuthorRecord:
    return AuthorRecord(
        position=position, name=ContributorName(raw=raw), identifiers={"orcid": orcid}
    )


def test_identifiant_partage_neutralise_sur_chaque_contribution_source():
    items = _items_written(
        [_record(0, "S. Acharya", "X"), _record(1, "S. Das", "X"), _record(2, "A. Kim", "Y")]
    )
    assert [i["neutralized_identifiers"] for i in items] == [
        {"orcid": "shared"},
        {"orcid": "shared"},
        None,
    ]


def test_collective_d_apres_la_source_ou_le_nom():
    items = _items_written(
        [
            AuthorRecord(position=0, name=ContributorName(raw="Big Lab"), collective=True),
            AuthorRecord(position=1, name=ContributorName(raw="ATLAS Collaboration")),
            AuthorRecord(position=2, name=ContributorName(raw="Tony Affolder")),
        ]
    )
    assert [i["collective"] for i in items] == [True, True, False]


def test_identifiants_bruts_conserves_sur_l_identite():
    items = _items_written([_record(0, "S. Acharya", "X"), _record(1, "S. Das", "X")])
    assert [i["identifiers"] for i in items] == [{"orcid": "X"}, {"orcid": "X"}]


class TestContributorNameFields:
    def test_nom_et_prenom_de_la_source(self):
        assert contributor_name_fields(ContributorName(last_name="Guérin", first_name="Katia")) == {
            "raw_author_name": None,
            "raw_last_name": "Guérin",
            "raw_first_name": "Katia",
            "last_name_normalized": "guerin",
            "first_name_normalized": "katia",
        }

    def test_chaine_brute_decoupee_par_le_parseur(self):
        assert contributor_name_fields(ContributorName(raw="Dupont, Marie")) == {
            "raw_author_name": "Dupont, Marie",
            "raw_last_name": None,
            "raw_first_name": None,
            "last_name_normalized": "dupont",
            "first_name_normalized": "marie",
        }

    def test_sans_prenom(self):
        fields = contributor_name_fields(ContributorName(last_name="Dupont"))
        assert (fields["last_name_normalized"], fields["first_name_normalized"]) == ("dupont", None)


def test_texte_d_adresse_assaini_a_la_construction():
    assert AddressRecord("  Labo A​ ").text == "Labo A"
