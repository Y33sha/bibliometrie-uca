"""Traduction des types de document des sources."""

import re
from pathlib import Path

import pytest

from domain.publications.doc_types import DOC_TYPES_SET
from domain.source_records.doc_types import _SOURCE_MAPS, map_doc_type

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = PROJECT_ROOT / "infrastructure" / "db" / "schema.sql"


def _read_pg_doc_type_enum() -> set[str]:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TYPE public\.doc_type AS ENUM\s*\(([^)]+)\)",
        sql,
    )
    assert match, "Enum doc_type introuvable dans schema.sql"
    return {m.group(1) for m in re.finditer(r"'([^']+)'", match.group(1))}


class TestDocTypeEnum:
    def test_doc_types_couvre_exactement_l_enum_pg(self):
        """`DOC_TYPES` a exactement les valeurs de l'enum PostgreSQL `doc_type`."""
        assert DOC_TYPES_SET == _read_pg_doc_type_enum()


class TestMapDocType:
    def test_hal_comm_vers_conference_paper(self):
        assert map_doc_type("comm", source="hal") == "conference_paper"

    def test_hal_proceedings_vers_conference_paper(self):
        assert map_doc_type("proceedings", source="hal") == "conference_paper"

    def test_hal_undefined_sans_sous_type_vers_preprint(self):
        assert map_doc_type("UNDEFINED", source="hal") == "preprint"

    def test_datacite_physicalobject_vers_physical_object(self):
        assert map_doc_type("PhysicalObject", source="datacite") == "physical_object"

    def test_datacite_texte_libre_technique_vers_report(self):
        assert map_doc_type("Technical note", source="datacite") == "report"
        assert map_doc_type("Technical Report", source="datacite") == "report"

    def test_datacite_presentation_vers_conference(self):
        assert map_doc_type("Presentation", source="datacite") == "conference"

    def test_videos_vers_recorded_talk(self):
        assert map_doc_type("VIDEO", source="hal") == "recorded_talk"
        assert map_doc_type("Audiovisual", source="datacite") == "recorded_talk"

    def test_enregistrements_audio_vers_media(self):
        assert map_doc_type("SON", source="hal") == "media"
        assert map_doc_type("Sound", source="datacite") == "media"

    def test_hal_these_d_exercice_par_le_diplome_dumas(self):
        assert map_doc_type("MEM_12", source="hal") == "practice_thesis"
        assert map_doc_type("MEM_30", source="hal") == "practice_thesis"

    def test_hal_sous_type_absent_de_la_table_prend_le_type(self):
        """Un mémoire de sage-femme (`MEM_14`) reste un mémoire."""
        assert map_doc_type("MEM_14", source="hal") == "memoir"
        assert map_doc_type("ART_unknown", source="hal") == "article"

    def test_hal_presconf_vers_conference(self):
        assert map_doc_type("PRESCONF", source="hal") == "conference"

    def test_hal_protocole_de_recherche_vers_report(self):
        assert map_doc_type("REPORT_RESPROT", source="hal") == "report"

    def test_openalex_conference_paper_vers_conference_paper(self):
        assert map_doc_type("conference-paper", source="openalex") == "conference_paper"

    def test_openalex_conference_abstract_vers_conference(self):
        assert map_doc_type("conference-abstract", source="openalex") == "conference"

    def test_wos_meeting_abstract_vers_conference(self):
        assert map_doc_type("Meeting Abstract", source="wos") == "conference"

    def test_wos_proceedings_paper_et_meeting_abstract_vers_conference_paper(self):
        assert (
            map_doc_type("Proceedings Paper; Meeting Abstract", source="wos") == "conference_paper"
        )

    def test_openalex_book_review_vers_book_review(self):
        assert map_doc_type("book-review", source="openalex") == "book_review"

    def test_openalex_data_paper_vers_data_paper(self):
        assert map_doc_type("data-paper", source="openalex") == "data_paper"

    def test_openalex_software_paper_vers_data_paper(self):
        """Un article décrivant un logiciel reste un article de données."""
        assert map_doc_type("software-paper", source="openalex") == "data_paper"

    def test_inconnu_vers_none(self):
        assert map_doc_type("foo_bar_baz", source="hal") is None

    def test_vide_vers_other(self):
        assert map_doc_type("", source="hal") == "other"

    def test_chaque_source_a_sa_nomenclature(self):
        """HAL range « proceedings » en communication, Crossref en actes."""
        assert map_doc_type("proceedings", source="crossref") == "proceedings"

    def test_une_valeur_absente_de_la_table_de_la_source_est_inconnue(self):
        """« dissertation » figure dans la table de DataCite, pas dans celle de HAL."""
        assert map_doc_type("dissertation", source="hal") is None

    def test_un_type_du_referentiel_se_traduit_par_lui_meme(self):
        assert map_doc_type("conference_paper", source="wos") == "conference_paper"


class TestMapDocTypeComposite:
    """Types composites WoS : le premier type significatif l'emporte."""

    def test_le_premier_type_l_emporte(self):
        assert map_doc_type("Article; Proceedings Paper", source="wos") == "article"

    def test_un_type_sans_signification_laisse_passer_le_suivant(self):
        assert map_doc_type("Note; Review", source="wos") == "review"

    def test_chaque_partie_se_lit_dans_la_nomenclature_de_la_source(self):
        assert map_doc_type("Proceedings; Other", source="crossref") == "proceedings"

    def test_des_types_tous_sans_signification_donnent_other(self):
        assert map_doc_type("Note; Reprint", source="wos") == "other"

    def test_un_composite_sans_partie_donne_other(self):
        assert map_doc_type(";", source="wos") == "other"

    def test_un_composite_de_parties_inconnues_est_inconnu(self):
        assert map_doc_type("Foo; Bar", source="wos") is None


_COMMON_TYPES = {
    "hal": ("ART", "COMM", "OUV", "COUV", "THESE", "HDR"),
    "openalex": (
        "article",
        "review",
        "book",
        "book-chapter",
        "proceedings-article",
        "preprint",
        "dissertation",
    ),
    "wos": ("article", "review", "book", "book chapter", "proceedings paper", "editorial material"),
    "crossref": (
        "journal-article",
        "book-chapter",
        "book",
        "monograph",
        "edited-book",
        "proceedings-article",
        "posted-content",
        "dissertation",
        "peer-review",
        "report",
    ),
}


class TestNomenclaturesDesSources:
    @pytest.mark.parametrize("source", sorted(_SOURCE_MAPS))
    def test_chaque_traduction_est_un_type_du_referentiel(self, source):
        assert set(_SOURCE_MAPS[source].values()) <= DOC_TYPES_SET

    @pytest.mark.parametrize(
        ("source", "raw"),
        [(source, raw) for source, types in _COMMON_TYPES.items() for raw in types],
    )
    def test_les_types_courants_sont_traduits(self, source, raw):
        assert map_doc_type(raw, source) not in (None, "other")
