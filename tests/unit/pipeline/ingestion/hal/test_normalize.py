"""Tests unitaires de `pipeline.ingestion.hal.normalize`.

Couvre les helpers (get_title, get_container_facts), `hal_source_record` (métadonnées canoniques, collections, biblio, keywords, NNT, topics), le parsing TEI, le parsing auteurs `build_hal_author_records` (composite + TEI) et les méthodes de `HalNormalizer` (métadonnées minimales, refus, éditeur, enregistrement source).

Pattern : doublures de stores + `MagicMock`, pas de DB.
"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import MagicMock

from domain.persons.contributor_name import ContributorName
from domain.serials.issns import IssnSupport, SerialIssn
from domain.source_records.biblio import PageRange
from domain.structures.identifiers import RorId
from pipeline.ingestion.common.normalizer import PublisherFacts
from pipeline.ingestion.hal import normalize as normalize_hal
from pipeline.ingestion.hal.normalize import (
    HalNormalizer,
    active_embargo_until,
    build_hal_author_records,
    build_hal_external_ids,
    extract_hal_author_block,
    get_container_facts,
    get_title,
    hal_source_record,
    page_range,
    parse_tei_isbns,
)
from pipeline.ingestion.hal.payload import hal_text_field
from pipeline.transformation.publishing.find_or_create import Containers
from tests.helpers.normalize_doubles import (
    FakeSourceContributionStore,
    FakeSourceRecordStore,
    FakeStagingStore,
    staging_row,
)

# ── Stubs ────────────────────────────────────────────────────────


# ── hal_text_field ───────────────────────────────────────────────────────


class TestAsStr:
    def test_none(self):
        assert hal_text_field(None) is None

    def test_empty_list(self):
        assert hal_text_field([]) is None

    def test_list_first(self):
        assert hal_text_field(["a", "b"]) == "a"

    def test_string_passthrough(self):
        assert hal_text_field("hello") == "hello"

    def test_non_str_coerced(self):
        assert hal_text_field(42) == "42"


# ── get_title ────────────────────────────────────────────────────


class TestGetTitle:
    def test_title_as_list(self):
        assert get_title({"title_s": ["My Title"]}) == "My Title"

    def test_title_as_string(self):
        assert get_title({"title_s": "Plain"}) == "Plain"

    def test_fallback_to_label(self):
        assert get_title({"label_s": "Fallback"}) == "Fallback"

    def test_empty(self):
        assert get_title({}) == ""

    def test_empty_title_list_falls_back_to_label(self):
        assert get_title({"title_s": [], "label_s": "L"}) == "L"


# ── conteneurs ───────────────────────────────────────────────────


class TestContainerDescription:
    def test_article_revue_et_ses_issn(self):
        facts = get_container_facts(
            {
                "docType_s": "ART",
                "journalTitle_s": "Nature",
                "journalIssn_s": "1234-5679",
                "journalEissn_s": "2345-6787",
            }
        )
        assert (facts.raw_doc_type, facts.journal_title) == ("ART", "Nature")
        assert facts.issns == (
            SerialIssn(issn="1234-5679", support=IssnSupport.PRINT),
            SerialIssn(issn="2345-6787", support=IssnSupport.ELECTRONIC),
        )

    def test_chapitre_livre_et_isbn(self):
        facts = get_container_facts(
            {
                "docType_s": "COUV",
                "title_s": ["Chapitre 3"],
                "bookTitle_s": "Le Paris du Moyen Âge",
                "label_xml": _embargo_tei('<idno type="isbn">978-2-410-01322-1</idno>'),
            }
        )
        assert facts.book_title == "Le Paris du Moyen Âge"
        assert facts.isbns == ("9782410013221",)

    def test_le_congres_d_une_communication_ne_designe_pas_un_volume(self):
        """Régression : une communication HAL nomme son congrès, avec ou sans actes publiés."""
        facts = get_container_facts({"docType_s": "COMM", "conferenceTitle_s": "NuFACT 2022"})
        assert facts.book_title is None

    def test_communication_a_isbn_nomme_son_volume_par_le_titre_de_source(self):
        facts = get_container_facts(
            {
                "docType_s": "COMM",
                "conferenceTitle_s": "Diplomacy and Political Communication in the West",
                "source_s": "Diplomacy and Political Communication in the West (III-I BC)",
                "label_xml": _embargo_tei('<idno type="isbn">978-84-1324-298-9</idno>'),
            }
        )
        assert facts.book_title == "Diplomacy and Political Communication in the West (III-I BC)"
        assert facts.isbns == ("9788413242989",)

    def test_communication_a_isbn_sans_titre_de_source_prend_le_congres(self):
        facts = get_container_facts(
            {
                "docType_s": "COMM",
                "conferenceTitle_s": "IC 2024",
                "label_xml": _embargo_tei('<idno type="isbn">978-3-031-33210-4</idno>'),
            }
        )
        assert facts.book_title == "IC 2024"


# ── métadonnées canoniques ───────────────────────────────────────────────


def _record(doc, containers=Containers(None, None)):
    return hal_source_record(doc, staging_id=1, hal_id="h1", containers=containers)


class TestCanonicalMetadata:
    def test_minimal(self):
        record = _record({"title_s": ["T"], "producedDateY_i": 2024}, Containers(42, None))
        assert record.title == "T"
        assert record.publication_year == 2024
        assert record.serial_id == 42
        # Pas de container_title si serial_id présent.
        assert record.container_title is None

    def test_book_title_fallback_when_no_serial(self):
        assert _record({"bookTitle_s": "Book"}).container_title == "Book"

    def test_conference_title_fallback(self):
        assert _record({"conferenceTitle_s": "Conf"}).container_title == "Conf"

    def test_serial_title_fallback_when_no_serial(self):
        """Un chapitre sans ISSN n'a pas de revue : son titre de revue reste en container_title."""
        record = _record({"docType_s": "COUV", "journalTitle_s": "Handbook"})
        assert record.container_title == "Handbook"

    def test_language_from_list(self):
        assert _record({"language_s": ["fr", "en"]}).raw_language == "fr"

    def test_no_language(self):
        assert _record({}).raw_language is None

    def test_nnt_normalized(self):
        record = _record({"nntId_s": "  2024CLFAC001  "})
        assert record.external_ids == {"hal_id": ["h1"], "nnt": "2024CLFAC001"}


# ── active_embargo_until ─────────────────────────────────────────


def _embargo_tei(refs: str) -> str:
    return f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>{refs}</body></text></TEI>'


def test_un_enregistrement_source_est_analyse_une_seule_fois(monkeypatch):
    """Régression : les lecteurs du TEI (conteneur, identifiants, embargo, auteurs) partagent une seule analyse."""
    calls = []
    real = normalize_hal.ET.fromstring
    monkeypatch.setattr(normalize_hal.ET, "fromstring", lambda x: calls.append(x) or real(x))
    normalize_hal._parse_tei.cache_clear()
    doc = {
        "docType_s": "COMM",
        "label_xml": _embargo_tei('<idno type="isbn">978-3-031-33210-4</idno>'),
    }
    get_container_facts(doc)
    build_hal_external_ids(doc, "hal-1", None)
    _record(doc)
    normalize_hal.parse_tei_author_identifiers(doc["label_xml"])
    assert len(calls) == 1


class TestParseTeiIsbns:
    """HAL ne donne l'ISBN que dans le TEI, et la zone contient parfois autre chose."""

    def test_reads_the_isbn_zone(self):
        xml = _embargo_tei('<idno type="isbn">978-3-031-33210-4</idno>')
        assert parse_tei_isbns(xml) == ["9783031332104"]

    def test_two_isbns_in_one_zone(self):
        xml = _embargo_tei('<idno type="isbn">978-3-030-34162-6 ; 978-3-030-34163-3</idno>')
        assert parse_tei_isbns(xml) == ["9783030341626", "9783030341633"]

    def test_other_idno_ignored(self):
        xml = _embargo_tei('<idno type="halId">hal-04434640</idno>')
        assert parse_tei_isbns(xml) == []

    def test_issn_in_the_zone_gives_nothing(self):
        assert parse_tei_isbns(_embargo_tei('<idno type="isbn">2055-0472</idno>')) == []

    def test_malformed_tei(self):
        assert parse_tei_isbns("<TEI") == []

    def test_no_label_xml(self):
        assert parse_tei_isbns(None) == []


class TestActiveEmbargoUntil:
    TODAY = date(2026, 6, 20)

    def test_future_file_embargo_returned(self):
        xml = _embargo_tei('<ref type="file" target="x"><date notBefore="2027-01-01"/></ref>')
        assert active_embargo_until(xml, self.TODAY) == date(2027, 1, 1)

    def test_past_embargo_is_none(self):
        # Date échue : pas d'embargo actif (fichier accessible).
        xml = _embargo_tei('<ref type="file" target="x"><date notBefore="2018-09-14"/></ref>')
        assert active_embargo_until(xml, self.TODAY) is None

    def test_multiple_files_take_latest(self):
        xml = _embargo_tei(
            '<ref type="file" target="a"><date notBefore="2026-12-01"/></ref>'
            '<ref type="file" target="b"><date notBefore="2027-03-01"/></ref>'
        )
        assert active_embargo_until(xml, self.TODAY) == date(2027, 3, 1)

    def test_non_file_ref_ignored(self):
        # Embargo sur une annexe (type='annex') : ignoré, seul le fichier compte.
        xml = _embargo_tei('<ref type="annex" target="x"><date notBefore="2027-01-01"/></ref>')
        assert active_embargo_until(xml, self.TODAY) is None

    def test_file_ref_without_date_is_none(self):
        assert (
            active_embargo_until(_embargo_tei('<ref type="file" target="x"/>'), self.TODAY) is None
        )

    def test_no_label_xml(self):
        assert active_embargo_until(None, self.TODAY) is None
        assert active_embargo_until("", self.TODAY) is None

    def test_malformed_xml_is_none(self):
        assert active_embargo_until("<not valid xml", self.TODAY) is None


# ── hal_source_record ────────────────────────────────────────────


class TestHalSourceRecord:
    def _call(self, doc, containers=Containers(None, None)):
        return _record(doc, containers)

    def test_collections_from_coll_codes(self):
        captured = self._call({"collCode_s": ["UCA", "LIMOS", "UCA"]})
        # Dédupliquées, triées, depuis le seul `collCode_s` du raw_data.
        assert captured.hal_collections == ["LIMOS", "UCA"]

    def test_no_collections_returns_none(self):
        captured = self._call({})
        assert captured.hal_collections is None

    def test_doc_type_concatenated_with_subtype(self):
        captured = self._call({"docType_s": "ART", "docSubType_s": "review"})
        assert captured.raw_doc_type == "ART_review"

    def test_doc_type_no_subtype(self):
        captured = self._call({"docType_s": "BOOK"})
        assert captured.raw_doc_type == "BOOK"

    def test_nnt_goes_in_external_ids(self):
        captured = self._call({"nntId_s": "2024CLFAC001"})
        assert captured.external_ids == {"hal_id": ["h1"], "nnt": "2024CLFAC001"}

    def test_hal_id_always_in_external_ids(self):
        """Le normalizer pose `external_ids.hal_id = source_id` même hors thèse, pour que `hal_id` soit un token de confirmation et que HAL soit clusterisé comme les autres sources (symétrie avec ce que theses fait déjà pour NNT)."""
        captured = self._call({})
        assert captured.external_ids == {"hal_id": ["h1"]}

    def test_keywords_deduplicated(self):
        captured = self._call({"keyword_s": ["a", "b", "a", "c"]})
        assert captured.keywords == ["a", "b", "c"]

    def test_keywords_empty(self):
        captured = self._call({"keyword_s": []})
        assert captured.keywords is None

    def test_topics_from_domain(self):
        """Les domaines sont stockés tels que la source les expose ; la découpe en libellés vit dans la phase `subjects`."""
        entries = [
            "sdv.bibs_FacetSep_Sciences du Vivant [q-bio]/Biostatistiques",
            "info.algo_FacetSep_Informatique [cs]/Algorithme et structure de données",
        ]
        captured = self._call({"fr_domainAllCodeLabel_fs": entries})
        assert captured.topics == {"hal_domains": entries}

    def test_biblio_built_from_volume_issue_pages(self):
        captured = self._call({"volume_s": "10", "issue_s": "2", "page_s": "100-120"})
        assert captured.biblio == {
            "volume": "10",
            "issue": "2",
            "first_page": "100",
            "last_page": "120",
        }

    def test_page_seule_d_un_livre_ecartee(self):
        assert page_range("288", "OUV") == PageRange()
        assert page_range("1449", "COUV") == PageRange()
        assert page_range("12-25", "COUV") == PageRange("12", "25")
        assert page_range("p. 29", "COUV") == PageRange("29")

    def test_page_seule_d_un_article_gardee(self):
        assert page_range("22045", "ART") == PageRange("22045")

    def test_biblio_empty(self):
        captured = self._call({})
        assert captured.biblio is None

    def test_biblio_publisher_from_journalPublisher_s(self):
        captured = self._call({"journalPublisher_s": "Elsevier"})
        assert captured.biblio == {"publisher": "Elsevier"}

    def test_biblio_publisher_fallback_to_publisher_s(self):
        captured = self._call({"publisher_s": "Springer"})
        assert captured.biblio == {"publisher": "Springer"}

    def test_biblio_journalPublisher_s_wins_over_publisher_s(self):
        captured = self._call({"journalPublisher_s": "Elsevier", "publisher_s": "Springer"})
        assert captured.biblio == {"publisher": "Elsevier"}

    def test_biblio_journal_built_from_title_issn_eissn(self):
        captured = self._call(
            {
                "journalTitle_s": "J. Phys.",
                "journalIssn_s": "0022-3727",
                "journalEissn_s": "1361-6463",
            },
        )
        assert captured.biblio == {
            "journal": {
                "title": "J. Phys.",
                "issn": "0022-3727",
                "eissn": "1361-6463",
            }
        }

    def test_biblio_journal_partial(self):
        captured = self._call({"journalTitle_s": "J. Phys."})
        assert captured.biblio == {"journal": {"title": "J. Phys."}}

    def test_url_from_uri(self):
        captured = self._call({"uri_s": "https://hal.science/hal-123"})
        assert captured.urls == ["https://hal.science/hal-123"]

    def test_propagates_containers_oa_embargo_lang(self):
        captured = self._call(
            {
                "fileMain_s": "https://hal.science/hal-123/document",
                "label_xml": _embargo_tei(
                    '<ref type="file" target="x"><date notBefore="2999-01-01"/></ref>'
                ),
                "language_s": "fr",
                "bookTitle_s": "Book",
            },
            Containers(None, 8),
        )
        assert captured.serial_id is None
        assert captured.monograph_id == 8
        assert captured.oa_status == "embargoed"
        assert captured.embargo_until == date(2999, 1, 1)
        assert captured.raw_language == "fr"
        assert captured.container_title == "Book"

    def test_serial_id_from_containers(self):
        assert self._call({}, Containers(7, None)).serial_id == 7


# `parse_tei_author_identifiers` est testé dans
# `tests/unit/application/test_parse_tei_author_identifiers.py` — pas de duplication ici.


# ── build_hal_author_records (parsing pur) ───────────────────────


class TestBuildHalAuthorRecords:
    def test_no_authors(self):
        assert build_hal_author_records({}) == []

    def test_skip_empty_name(self):
        records = build_hal_author_records(
            {
                "authFullNameFormIDPersonIDIDHal_fs": [
                    "_FacetSep_0-0_FacetSep_",
                    "Marie Dupont_FacetSep_0-0_FacetSep_",
                ]
            }
        )
        assert len(records) == 1
        assert records[0].name == ContributorName(raw="Marie Dupont")

    def test_composite_extracts_name_and_hal_person_id(self):
        # Le composite fournit le nom et le hal_person_id (2e segment). L'idhal
        # vient du TEI, pas du composite (cf. test suivant).
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Marie Dupont_FacetSep_49236-749496_FacetSep_marie-dupont"
            ],
        }
        record = build_hal_author_records(doc)[0]
        # Pas de TEI → nom Solr en chaîne brute, pas d'idhal (le 3e segment du composite est ignoré).
        assert record.name == ContributorName(raw="Marie Dupont")
        assert record.identifiers == {"hal_person_id": "749496"}

    def test_nom_et_prenom_viennent_du_tei(self):
        label_xml = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><biblFull><titleStmt>'
            "<author><persName><forename>Marie</forename><surname>Caldefie Chezet</surname>"
            "</persName></author></titleStmt></biblFull></TEI>"
        )
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Marie Caldefie Chezet_FacetSep_49236-749496_FacetSep_"
            ],
            "label_xml": label_xml,
        }
        assert build_hal_author_records(extract_hal_author_block(doc))[0].name == ContributorName(
            last_name="Caldefie Chezet", first_name="Marie"
        )

    def test_idhal_comes_from_tei(self):
        # L'idhal slug vient du TEI (notation="string"), aligné par position.
        label_xml = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><biblFull><titleStmt>'
            '<author><idno type="idhal" notation="string">marie-dupont</idno></author>'
            "</titleStmt></biblFull></TEI>"
        )
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Marie Dupont_FacetSep_49236-749496_FacetSep_marie-dupont"
            ],
            "label_xml": label_xml,
        }
        assert build_hal_author_records(extract_hal_author_block(doc))[0].identifiers == {
            "idhal": "marie-dupont",
            "hal_person_id": "749496",
        }

    def test_composite_numeric_idhal_not_promoted(self):
        # Régression : quand l'auteur n'a pas de slug, HAL recopie le person_id
        # numérique dans le 3e segment du composite. Sans idhal TEI, on ne doit
        # PAS créer d'idhal numérique (== hal_person_id) — seul hal_person_id reste.
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Christian Duale_FacetSep_106-921527_FacetSep_921527"
            ],
        }
        assert build_hal_author_records(doc)[0].identifiers == {
            "hal_person_id": "921527",
        }

    def test_composite_with_zero_person_id_filtered(self):
        """person_id == 0 = non identifié par HAL, on l'ignore."""
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": ["X_FacetSep_49236-0_FacetSep_"],
        }
        # Sans hal_person_id ni idhal, identifiers est None.
        assert build_hal_author_records(doc)[0].identifiers is None

    def test_duplicate_hal_person_id_kept_on_each_record(self):
        """La lecture rend les identifiants de chaque auteur tels que le dépôt les donne, compte HAL et IdRef alignés par position ; le writer neutralise ceux que partagent plusieurs contributions sources."""
        label_xml = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><biblFull><titleStmt>'
            '<author><idno type="IDREF">111111111</idno></author>'
            '<author><idno type="IDREF">111111111</idno></author>'
            "<author></author>"
            "</titleStmt></biblFull></TEI>"
        )
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Marie Dupont_FacetSep_49236-749496_FacetSep_",
                "Jean Martin_FacetSep_10000-749496_FacetSep_",
                "Sophie Bernard_FacetSep_20000-555_FacetSep_",
            ],
            "label_xml": label_xml,
        }
        records = build_hal_author_records(extract_hal_author_block(doc))
        assert records[0].identifiers == {"hal_person_id": "749496", "idref": "111111111"}
        assert records[1].identifiers == {"hal_person_id": "749496", "idref": "111111111"}
        assert records[2].identifiers == {"hal_person_id": "555"}

    def test_structures_from_tei_without_address(self):
        """Les structures HAL et leurs ROR, lus dans le TEI, vont sur la contribution source ; la contribution source est sans adresse."""
        block = {
            "authFullNameFormIDPersonIDIDHal_fs": ["X_FacetSep_49236-749496_FacetSep_"],
            "tei_author_rors": [["https://ror.org/03vgfxd91"]],
            "tei_author_structures": [[300012]],
        }
        record = build_hal_author_records(block)[0]
        assert record.addresses == []
        assert record.hal_structure_ids == {300012}
        assert record.ror_ids == {RorId("03vgfxd91")}

    def test_quality_maps_to_roles(self):
        """`authQuality_s = 'dir'` est mappé en rôle via `map_role('hal', ...)` (cf. domain.publications.contribution_roles)."""
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": ["Director_FacetSep_0-0_FacetSep_"],
            "authQuality_s": ["dir"],
        }
        record = build_hal_author_records(doc)[0]
        # On valide juste que map_role a été appelé et a produit une liste non-vide.
        assert record.roles is not None
        assert len(record.roles) > 0


# ── HalNormalizer (classe) ───────────────────────────────────────


def _make_normalizer():
    return HalNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_store=FakeStagingStore(),
        record_store=FakeSourceRecordStore(),
        container_stores=MagicMock(),
        publisher_store=MagicMock(),
        contribution_store=FakeSourceContributionStore(),
        location_store=MagicMock(),
    )


class TestHalNormalizerClass:
    def test_metadonnees_minimales(self):
        norm = _make_normalizer()
        assert norm.minimal_metadata(staging_row(raw={"title_s": []})) == ("", None)
        assert norm.minimal_metadata(
            staging_row(raw={"title_s": ["T"], "producedDateY_i": 2024})
        ) == ("T", 2024)

    def test_refuse_sans_champ_auteurs(self):
        """Métadonnées minimales présentes, champ auteurs absent : enregistrement source refusé."""
        row = staging_row(raw={"title_s": ["T"], "producedDateY_i": 2024})
        assert _make_normalizer().parse(row) is None

    def test_accepte_avec_champ_auteurs(self):
        raw = {"title_s": ["T"], "authFullNameFormIDPersonIDIDHal_fs": ["T_FacetSep_0-0_FacetSep_"]}
        assert _make_normalizer().parse(staging_row(raw=raw)) == raw

    def test_editeur_de_journalPublisher_s_puis_publisher_s(self):
        norm = _make_normalizer()
        assert norm.publisher({"journalPublisher_s": "Elsevier", "publisher_s": "Springer"}) == (
            PublisherFacts("Elsevier")
        )
        assert norm.publisher({"publisher_s": "Springer"}) == PublisherFacts("Springer")

    def test_sans_editeur(self):
        assert _make_normalizer().publisher({}) is None

    def test_enregistrement_source_porte_ligne_et_conteneurs(self):
        row = staging_row(staging_id=7, source_id="hal-7", raw={"title_s": ["T"]})
        record = _make_normalizer().source_record(row, row.raw_data, Containers(3, 4))
        assert (record.staging_id, record.source_id) == (7, "hal-7")
        assert (record.serial_id, record.monograph_id) == (3, 4)
