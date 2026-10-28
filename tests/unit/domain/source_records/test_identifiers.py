"""Normalisation des identifiants d'un enregistrement source et `external_ids` qui s'en déduit."""

from domain.source_records.external_ids import external_ids_from_identifiers
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    isbn_role,
    normalize_identifiers,
)

T, R = SourceIdentifierType, SourceIdentifierRole


class TestNormalizeIdentifiers:
    def test_valeur_normalisee_et_valeur_invalide_ecartee(self):
        invalid = SourceIdentifier(T.PMID, "pas un pmid", R.SECONDARY)
        kept, rejected = normalize_identifiers(
            [SourceIdentifier(T.DOI, "https://doi.org/10.1/X", R.PRIMARY), invalid]
        )
        assert kept == (SourceIdentifier(T.DOI, "10.1/x", R.PRIMARY),)
        assert rejected == (invalid,)

    def test_doublon_garde_sa_place_et_son_role_le_plus_fort(self):
        kept, _ = normalize_identifiers(
            [
                SourceIdentifier(T.HAL_ID, "hal-01000001", R.SECONDARY),
                SourceIdentifier(T.HAL_ID, "hal-01000002", R.SECONDARY),
                SourceIdentifier(T.HAL_ID, "hal-01000001v2", R.DERIVED),
            ]
        )
        assert kept == (
            SourceIdentifier(T.HAL_ID, "hal-01000001", R.DERIVED),
            SourceIdentifier(T.HAL_ID, "hal-01000002", R.SECONDARY),
        )

    def test_chaque_type_passe_par_son_value_object(self):
        kept, rejected = normalize_identifiers(
            [
                SourceIdentifier(T.HAL_ID, "https://hal.science/hal-04123456v2", R.SECONDARY),
                SourceIdentifier(T.HAL_ID, "sic_01848892", R.SECONDARY),
                SourceIdentifier(T.NNT, "2021clfa0030", R.SECONDARY),
                SourceIdentifier(T.ISBN, "0306406152", R.SECONDARY),
                SourceIdentifier(T.ISBN, "978-0-00-000000-1", R.SECONDARY),
            ]
        )
        assert [i.value for i in kept] == [
            "hal-04123456",
            "sic_01848892",
            "2021CLFA0030",
            "9780306406157",
        ]
        assert [i.value for i in rejected] == ["978-0-00-000000-1"]

    def test_idempotent(self):
        kept, _ = normalize_identifiers([SourceIdentifier(T.HAL_ID, "HAL-04123456v1", R.PRIMARY)])
        assert normalize_identifiers(kept) == (kept, ())


class TestIsbnRole:
    def test_secondaire_pour_un_livre(self):
        assert isbn_role("book", "crossref") is R.SECONDARY

    def test_lie_pour_un_chapitre_ou_un_article_de_congres(self):
        assert isbn_role("book-chapter", "crossref") is R.RELATED
        assert isbn_role("book", "crossref", declares_conference=True) is R.RELATED


class TestExternalIdsFromIdentifiers:
    def test_related_dois_hors_doi_de_la_colonne(self):
        identifiers = [
            SourceIdentifier(T.DOI, "10.1/x", R.PRIMARY),
            SourceIdentifier(T.DOI, "10.2/y", R.RELATED),
        ]
        assert external_ids_from_identifiers(identifiers, "10.1/x") == {"related_dois": ["10.2/y"]}

    def test_types_multivalues_tries_par_role_puis_par_valeur(self):
        identifiers = [
            SourceIdentifier(T.HAL_ID, "hal-3", R.SECONDARY),
            SourceIdentifier(T.HAL_ID, "hal-2", R.SECONDARY),
            SourceIdentifier(T.HAL_ID, "hal-9", R.DERIVED),
        ]
        assert external_ids_from_identifiers(identifiers, None) == {
            "hal_id": ["hal-9", "hal-2", "hal-3"]
        }

    def test_identifiant_retire_absent(self):
        identifiers = [
            SourceIdentifier(T.HAL_ID, "hal-1", R.SECONDARY, "HAL_DEPOSIT_MISSING_TO_REMOVED"),
            SourceIdentifier(T.HAL_ID, "hal-2", R.SECONDARY),
        ]
        assert external_ids_from_identifiers(identifiers, None) == {"hal_id": ["hal-2"]}

    def test_type_a_valeur_unique_prend_le_role_le_plus_fort(self):
        identifiers = [
            SourceIdentifier(T.NNT, "2020AAAA0001", R.SECONDARY),
            SourceIdentifier(T.NNT, "2021BBBB0002", R.DERIVED),
            SourceIdentifier(T.PMID, "1", R.SECONDARY),
            SourceIdentifier(T.PMID, "2", R.SECONDARY),
        ]
        assert external_ids_from_identifiers(identifiers, None) == {
            "nnt": "2021BBBB0002",
            "pmid": "1",
        }
