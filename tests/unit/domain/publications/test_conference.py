"""Communication ou texte publié dans des actes (`domain.publications.conference`)."""

from domain.publications.conference import arbitrate_conference, attests_publication
from domain.source_records.source_record import SourceRecord


def _source_record(**overrides) -> SourceRecord:
    defaults = {
        "id": 1,
        "source": "hal",
        "source_id": "hal-1",
        "title": "Titre",
        "publication_year": 2020,
        "doc_type": "conference_paper",
        "doi": None,
        "serial_id": None,
        "monograph_id": None,
        "container_title": "Colloque de 2020",
        "language": None,
        "oa_status": None,
        "is_retracted": None,
        "abstract": None,
        "countries": (),
        "keywords": (),
        "urls": (),
        "topics": None,
        "biblio": None,
        "source_extras": None,
    }
    defaults.update(overrides)
    return SourceRecord(**defaults)  # type: ignore[arg-type]


class TestAttestsPublication:
    def test_trace_en_base(self):
        assert attests_publication(_source_record(doi="10.1/x"))
        assert attests_publication(_source_record(serial_id=3))
        assert attests_publication(_source_record(monograph_id=4))

    def test_congres_declare_par_crossref(self):
        assert attests_publication(
            _source_record(source="crossref", source_extras={"conference": {"name": "ICRA"}})
        )

    def test_champs_editoriaux_hal(self):
        assert attests_publication(_source_record(source_extras={"proceedings": True}))
        assert attests_publication(_source_record(biblio={"first_page": "465", "last_page": "470"}))
        assert attests_publication(_source_record(biblio={"publisher": "Dykinson S. L."}))
        assert attests_publication(
            _source_record(source_extras={"source_title": "Actes des 8èmes journées"})
        )

    def test_bruit_hal_sans_valeur(self):
        assert not attests_publication(_source_record(source_extras={"proceedings": False}))
        assert not attests_publication(
            _source_record(biblio={"first_page": "21", "publisher": "s.n."})
        )
        assert not attests_publication(
            _source_record(source_extras={"source_title": "Colloque de 2020"})
        )

    def test_champs_editoriaux_ignores_hors_hal(self):
        assert not attests_publication(
            _source_record(source="openalex", biblio={"publisher": "HAL CCSD"})
        )


class TestArbitrateConference:
    def test_communication_hal_sans_attestation_ni_echo(self):
        sources = [
            _source_record(),
            _source_record(id=2, source="scanr"),
            _source_record(id=3, source="openalex"),
        ]
        assert arbitrate_conference("conference_paper", sources) == "conference"

    def test_attestation_d_une_autre_source(self):
        sources = [
            _source_record(),
            _source_record(id=2, source="openalex", doi="10.1109/icra.2021.1"),
        ]
        assert arbitrate_conference("conference_paper", sources) == "conference_paper"

    def test_resume_designe_par_une_source_l_emporte(self):
        sources = [
            _source_record(
                source="crossref", doc_type="preprint", doi="10.5194/egusphere-egu21-8391"
            ),
            _source_record(id=2, source="openalex", doc_type="conference"),
        ]
        assert arbitrate_conference("preprint", sources) == "conference"

    def test_resume_en_supplement_de_revue(self):
        sources = [
            _source_record(
                source="crossref", doc_type="article", serial_id=7, doi="10.1182/blood-2020"
            ),
            _source_record(id=2, source="wos", doc_type="conference", serial_id=7),
        ]
        assert arbitrate_conference("article", sources) == "conference"

    def test_recueil_de_resumes_hal(self):
        sources = [
            _source_record(source_extras={"source_title": "Book of abstracts", "proceedings": True})
        ]
        assert arbitrate_conference("conference_paper", sources) == "conference"

    def test_autres_types_inchanges(self):
        sources = [
            _source_record(doc_type="book_chapter"),
            _source_record(id=2, source="openalex", doc_type="conference"),
        ]
        assert arbitrate_conference("book_chapter", sources) == "book_chapter"
