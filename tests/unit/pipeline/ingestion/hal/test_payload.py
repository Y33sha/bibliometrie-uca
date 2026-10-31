from pipeline.ingestion.hal.payload import (
    extract_hal_source_extras,
    hal_text_field,
)


class TestHalTextField:
    def test_non_textual_first_value_is_rendered_as_text(self):
        assert hal_text_field([123, "suite"]) == "123"


class TestExtractHalMeta:
    def test_indicateur_actes_series_et_titre_de_source(self):
        doc = {
            "proceedings_s": "1",
            "serie_s": ["Occidens (3)", " ", "Occidens (3)"],
            "source_s": "Actes des 8èmes journées scientifiques",
        }
        assert extract_hal_source_extras(doc) == {
            "proceedings": True,
            "series": ["Occidens (3)"],
            "source_title": "Actes des 8èmes journées scientifiques",
        }

    def test_sans_actes(self):
        assert extract_hal_source_extras({"proceedings_s": "0"}) == {"proceedings": False}

    def test_licence_du_fichier_depose(self):
        doc = {"licence_s": "https://creativecommons.org/licenses/by/4.0/"}
        assert extract_hal_source_extras(doc) == {
            "licence": "https://creativecommons.org/licenses/by/4.0/"
        }

    def test_enregistrement_source_muet(self):
        assert extract_hal_source_extras({"title_s": ["Titre"]}) is None
