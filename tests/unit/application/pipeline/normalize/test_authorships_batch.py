"""Tests du writer partagé des signatures : neutralisation des identifiants partagés dans un document."""

from unittest.mock import MagicMock

from application.pipeline.normalize._authorships_batch import (
    AuthorRecord,
    write_source_authorships,
)


def _items_written(records: list[AuthorRecord]) -> list[dict]:
    queries = MagicMock()
    write_source_authorships(MagicMock(), queries, "crossref", 1, records)
    return queries.upsert_source_authorships_batch.call_args.args[1]


def test_identifiant_partage_neutralise_sur_chaque_signature():
    items = _items_written(
        [
            AuthorRecord(position=0, raw_name="S. Acharya", person_identifiers={"orcid": "X"}),
            AuthorRecord(position=1, raw_name="S. Das", person_identifiers={"orcid": "X"}),
            AuthorRecord(position=2, raw_name="A. Kim", person_identifiers={"orcid": "Y"}),
        ]
    )
    assert [i["neutralized_identifiers"] for i in items] == [
        {"orcid": "shared"},
        {"orcid": "shared"},
        None,
    ]


def test_identifiants_bruts_conserves_sur_l_identite():
    items = _items_written(
        [
            AuthorRecord(position=0, raw_name="S. Acharya", person_identifiers={"orcid": "X"}),
            AuthorRecord(position=1, raw_name="S. Das", person_identifiers={"orcid": "X"}),
        ]
    )
    assert [i["person_identifiers"] for i in items] == [{"orcid": "X"}, {"orcid": "X"}]
