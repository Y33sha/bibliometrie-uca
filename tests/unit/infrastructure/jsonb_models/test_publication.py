"""Tests des modèles JSONB de infrastructure/jsonb_models/publication.py."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from application.ports.api.publications_queries import EcoleDoctorale, PartenaireThese
from infrastructure.jsonb_models.publication import (
    ExternalIds,
    OpenAlexTopic,
    PublicationBiblio,
    PublicationMeta,
    PublicationTopics,
    ThesesTopics,
)

# ── ExternalIds ────────────────────────────────────────────────────


class TestExternalIdsParsing:
    def test_empty(self):
        ids = ExternalIds()
        assert ids.hal_id is None
        assert ids.nnt is None
        assert ids.pmid is None
        assert ids.pmcid is None
        assert ids.arxiv_id is None
        assert ids.related_dois is None

    def test_from_dict_basic(self):
        ids = ExternalIds(
            hal_id="hal-04123456",
            nnt="2021clfa0030",
            pmid="12345",
            pmcid="987654",
            arxiv_id="https://arxiv.org/abs/2401.00123",
        )
        assert ids.hal_id == ["hal-04123456"]
        assert ids.nnt == "2021CLFA0030"  # normalisé en majuscules
        assert ids.pmid == "12345"
        assert ids.pmcid == "PMC987654"  # préfixe PMC ajouté
        assert ids.arxiv_id == "2401.00123"  # URL → id canonique

    def test_normalize_hal_url(self):
        """Une URL HAL en entrée (scalaire toléré) est normalisée en ID canonique, en liste."""
        ids = ExternalIds(hal_id="https://hal.science/hal-04123456v2")
        assert ids.hal_id == ["hal-04123456"]

    def test_hal_id_list_normalized_and_deduped(self):
        ids = ExternalIds(
            hal_id=["https://hal.science/hal-04000111v2", "hal-04000222", "hal-04000111"]
        )
        assert ids.hal_id == ["hal-04000111", "hal-04000222"]

    def test_related_dois_normalized_and_deduped(self):
        ids = ExternalIds(related_dois=["https://doi.org/10.1/X", "10.2/y", "10.1/x"])
        assert ids.related_dois == ["10.1/x", "10.2/y"]

    def test_related_dois_scalar_tolerated(self):
        ids = ExternalIds(related_dois="10.1/x")
        assert ids.related_dois == ["10.1/x"]

    def test_invalid_related_doi_raises(self):
        with pytest.raises(PydanticValidationError):
            ExternalIds(related_dois=["https://doi.org/"])

    def test_empty_string_treated_as_none(self):
        ids = ExternalIds(hal_id="", nnt="")
        assert ids.hal_id is None
        assert ids.nnt is None

    def test_invalid_hal_raises(self):
        with pytest.raises(PydanticValidationError):
            ExternalIds(hal_id="garbage-not-hal")

    def test_invalid_nnt_raises(self):
        with pytest.raises(PydanticValidationError):
            ExternalIds(nnt="   ")  # blanc après strip, vide = invalide

    def test_accepts_extra_keys(self):
        """Les clés non déclarées (futures évolutions) sont conservées telles quelles."""
        ids = ExternalIds(hal_id="hal-04001234", mag="2912345678", issn="0028-0836")
        # Les extras sont accessibles via model_extra
        dumped = ids.to_dict()
        assert dumped["mag"] == "2912345678"
        assert dumped["issn"] == "0028-0836"

    def test_to_dict_omits_none(self):
        ids = ExternalIds(hal_id="hal-04001234")
        dumped = ids.to_dict()
        assert dumped == {"hal_id": ["hal-04001234"]}  # nnt/pmid/pmcid/arxiv_id omis car None

    def test_roundtrip_from_db(self):
        """Simule un aller-retour : lecture depuis BD (dict) → model → retour dict."""
        from_db = {"hal_id": ["hal-04123456"], "nnt": "2021CLFA0030", "pmid": "12345678"}
        ids = ExternalIds(**from_db)
        back = ids.to_dict()
        assert back == from_db


# ── PublicationBiblio ──────────────────────────────────────────────


class TestPublicationBiblio:
    def test_hal_style_pages_range(self):
        b = PublicationBiblio(volume="42", issue="3", pages="123-145")
        assert b.to_dict() == {"volume": "42", "issue": "3", "pages": "123-145"}

    def test_openalex_style_decomposed(self):
        b = PublicationBiblio(volume="42", issue="3", first_page="123", last_page="145")
        assert b.to_dict() == {
            "volume": "42",
            "issue": "3",
            "first_page": "123",
            "last_page": "145",
        }

    def test_mixed_schemas_tolerated(self):
        """Après fusion entre HAL et OpenAlex, les deux schémas peuvent
        coexister dans le même enregistrement. Le modèle le tolère."""
        b = PublicationBiblio(pages="123-145", first_page="123", last_page="145")
        d = b.to_dict()
        assert "pages" in d and "first_page" in d and "last_page" in d

    def test_allows_extra_keys(self):
        b = PublicationBiblio(volume="42", article_number="e12345")
        assert b.to_dict()["article_number"] == "e12345"

    def test_empty(self):
        assert PublicationBiblio().to_dict() == {}


# ── PublicationMeta ────────────────────────────────────────────────


class TestPublicationMeta:
    def test_thesis_minimal(self):
        m = PublicationMeta(
            date_soutenance="2023-06-15",
            discipline="Informatique",
        )
        d = m.to_dict()
        assert d["date_soutenance"] == "2023-06-15"
        assert d["discipline"] == "Informatique"

    def test_with_structured_sub_objects(self):
        m = PublicationMeta(
            discipline="Mathématiques",
            ecoles_doctorales=[{"nom": "ED SPI", "ppn": "123456789"}],
            partenaires=[{"nom": "CNRS", "type": "etablissement"}],
        )
        d = m.to_dict()
        assert d["ecoles_doctorales"][0]["nom"] == "ED SPI"
        assert d["ecoles_doctorales"][0]["ppn"] == "123456789"
        assert d["partenaires"][0]["type"] == "etablissement"

    def test_ecole_doctorale_without_ppn(self):
        ed = EcoleDoctorale(nom="ED SPI")
        # Le ppn est optionnel
        assert ed.ppn is None

    def test_ecole_doctorale_requires_nom(self):
        with pytest.raises(PydanticValidationError):
            EcoleDoctorale()  # nom obligatoire

    def test_partenaire_requires_nom(self):
        with pytest.raises(PydanticValidationError):
            PartenaireThese()  # nom obligatoire


# ── PublicationTopics ──────────────────────────────────────────────


class TestPublicationTopics:
    def test_openalex_list_preserved(self):
        """La liste OpenAlex est conservée telle quelle sous la clé openalex."""
        t = PublicationTopics(
            openalex=[
                {
                    "domain": "SS",
                    "field": "Eco",
                    "subfield": "Micro",
                    "topic": "Behav",
                    "score": 0.95,
                },
                {"domain": "CS", "field": "AI", "subfield": "ML", "topic": "DL", "score": 0.87},
            ]
        )
        d = t.to_dict()
        assert isinstance(d["openalex"], list)
        assert len(d["openalex"]) == 2
        assert d["openalex"][0]["domain"] == "SS"
        assert d["openalex"][0]["score"] == 0.95

    def test_theses_dict_preserved(self):
        t = PublicationTopics(theses={"discipline": "Informatique", "rameau": ["Algorithmes"]})
        d = t.to_dict()
        assert d["theses"]["discipline"] == "Informatique"
        assert d["theses"]["rameau"] == ["Algorithmes"]

    def test_composite_multiple_sources(self):
        """Le cas principal : OpenAlex + theses coexistent sans collision."""
        t = PublicationTopics(
            openalex=[{"topic": "Behav", "score": 0.9}],
            theses={"discipline": "Info", "rameau": ["Algo"]},
        )
        d = t.to_dict()
        assert "openalex" in d
        assert "theses" in d

    def test_scanr_arbitrary(self):
        """ScanR a une structure variable — on accepte dict brut."""
        t = PublicationTopics(scanr={"domains": ["cs", "math"], "weird_key": "ok"})
        d = t.to_dict()
        assert d["scanr"]["domains"] == ["cs", "math"]

    def test_openalex_topic_optional_fields(self):
        """Les champs OpenAlex sont tous optionnels — données réelles parfois
        incomplètes."""
        topic = OpenAlexTopic(domain="Sciences")
        assert topic.domain == "Sciences"
        assert topic.field is None
        assert topic.score is None

    def test_theses_topics_minimal(self):
        t = ThesesTopics()
        assert t.discipline is None
        assert t.rameau is None

    def test_empty(self):
        assert PublicationTopics().to_dict() == {}
