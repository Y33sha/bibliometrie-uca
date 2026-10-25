"""Tests du mapping doc_types et cohérence des libellés FR frontend."""

import re
from pathlib import Path

from domain.publications.doc_types import DOC_TYPES_SET
from domain.source_records.doc_types import map_doc_type

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = PROJECT_ROOT / "infrastructure" / "db" / "schema.sql"
LABELS_PATH = PROJECT_ROOT / "interfaces" / "frontend" / "src" / "lib" / "labels.ts"


def _read_pg_doc_type_enum() -> set[str]:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TYPE public\.doc_type AS ENUM\s*\(([^)]+)\)",
        sql,
    )
    assert match, "Enum doc_type introuvable dans schema.sql"
    return {m.group(1) for m in re.finditer(r"'([^']+)'", match.group(1))}


def _read_ts_label_map(var_name: str) -> dict[str, str]:
    """Extrait `export const <var_name>: Record<...> = { ... }` de labels.ts.

    Même approche que la lecture de l'enum dans schema.sql : on parse le
    fichier frontend pour vérifier que les libellés codés en dur restent
    alignés sur l'enum PG / `DOC_TYPES` sans devoir exécuter le frontend.
    """
    ts = LABELS_PATH.read_text(encoding="utf-8")
    block = re.search(
        rf"export const {var_name}: Record<string, string> = \{{(.*?)\}};",
        ts,
        re.DOTALL,
    )
    assert block, f"Map {var_name} introuvable dans labels.ts"
    return {m.group(1): m.group(3) for m in re.finditer(r"(\w+):\s*(['\"])(.*?)\2", block.group(1))}


class TestDocTypeEnum:
    def test_doc_types_couvre_exactement_l_enum_pg(self):
        """Garde-fou : `DOC_TYPES` doit refléter exactement l'enum PG."""
        assert DOC_TYPES_SET == _read_pg_doc_type_enum()


class TestDocTypeLabelsFrontend:
    def test_singulier_couvre_exactement_les_doc_types(self):
        """Tout doc_type doit avoir son libellé singulier côté frontend."""
        assert set(_read_ts_label_map("docTypeSingular").keys()) == DOC_TYPES_SET

    def test_pluriel_couvre_exactement_les_doc_types(self):
        """Tout doc_type doit avoir son libellé pluriel côté frontend."""
        assert set(_read_ts_label_map("docTypePlural").keys()) == DOC_TYPES_SET

    def test_libelles_non_vides(self):
        for var_name in ("docTypeSingular", "docTypePlural"):
            for value, label in _read_ts_label_map(var_name).items():
                assert label, f"Libellé vide pour {value} dans {var_name}"


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
