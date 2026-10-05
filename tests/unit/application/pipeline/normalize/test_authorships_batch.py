"""Tests du writer partagé des signatures : neutralisation des identifiants partagés dans un document, colonnes de nom."""

from unittest.mock import MagicMock

from application.pipeline.normalize._authorships_batch import (
    AuthorRecord,
    signature_name_fields,
    write_source_authorships,
)
from domain.persons.signature_name import SignatureName
from infrastructure.fingerprint import fingerprint


def _items_written(records: list[AuthorRecord]) -> list[dict]:
    queries = MagicMock()
    write_source_authorships(MagicMock(), queries, fingerprint, "crossref", 1, records)
    return queries.upsert_source_authorships_batch.call_args.args[1]


def _record(position: int, raw: str, orcid: str) -> AuthorRecord:
    return AuthorRecord(
        position=position, name=SignatureName(raw=raw), person_identifiers={"orcid": orcid}
    )


def test_identifiant_partage_neutralise_sur_chaque_signature():
    items = _items_written(
        [_record(0, "S. Acharya", "X"), _record(1, "S. Das", "X"), _record(2, "A. Kim", "Y")]
    )
    assert [i["neutralized_identifiers"] for i in items] == [
        {"orcid": "shared"},
        {"orcid": "shared"},
        None,
    ]


def test_identifiants_bruts_conserves_sur_l_identite():
    items = _items_written([_record(0, "S. Acharya", "X"), _record(1, "S. Das", "X")])
    assert [i["person_identifiers"] for i in items] == [{"orcid": "X"}, {"orcid": "X"}]


class TestSignatureNameFields:
    def test_nom_et_prenom_de_la_source(self):
        assert signature_name_fields(SignatureName(last_name="Guérin", first_name="Katia")) == {
            "raw_author_name": None,
            "raw_last_name": "Guérin",
            "raw_first_name": "Katia",
            "last_name_normalized": "guerin",
            "first_name_normalized": "katia",
            "author_name_normalized": "katia guerin",
        }

    def test_chaine_brute_decoupee_par_le_parseur(self):
        assert signature_name_fields(SignatureName(raw="Dupont, Marie")) == {
            "raw_author_name": "Dupont, Marie",
            "raw_last_name": None,
            "raw_first_name": None,
            "last_name_normalized": "dupont",
            "first_name_normalized": "marie",
            "author_name_normalized": "marie dupont",
        }

    def test_sans_prenom(self):
        fields = signature_name_fields(SignatureName(last_name="Dupont"))
        assert (fields["first_name_normalized"], fields["author_name_normalized"]) == (
            None,
            "dupont",
        )
