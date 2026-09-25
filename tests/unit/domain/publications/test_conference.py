"""Communication ou texte publié dans des actes (`domain.publications.conference`)."""

from domain.publications.conference import arbitrate_conference, attests_publication
from domain.source_publications.source_publication import SourcePublication


def _sp(**overrides) -> SourcePublication:
    defaults = {
        "id": 1,
        "source": "hal",
        "source_id": "hal-1",
        "title": "Titre",
        "pub_year": 2020,
        "doc_type": "conference_paper",
        "doi": None,
        "journal_id": None,
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
        "meta": None,
    }
    defaults.update(overrides)
    return SourcePublication(**defaults)  # type: ignore[arg-type]


class TestAttestsPublication:
    def test_trace_en_base(self):
        assert attests_publication(_sp(doi="10.1/x"))
        assert attests_publication(_sp(journal_id=3))
        assert attests_publication(_sp(monograph_id=4))

    def test_congres_declare_par_crossref(self):
        assert attests_publication(_sp(source="crossref", meta={"conference": {"name": "ICRA"}}))

    def test_champs_editoriaux_hal(self):
        assert attests_publication(_sp(meta={"proceedings": True}))
        assert attests_publication(_sp(biblio={"pages": "pp. 465-470"}))
        assert attests_publication(_sp(biblio={"publisher": "Dykinson S. L."}))
        assert attests_publication(_sp(meta={"source_title": "Actes des 8èmes journées"}))

    def test_bruit_hal_sans_valeur(self):
        assert not attests_publication(_sp(meta={"proceedings": False}))
        assert not attests_publication(_sp(biblio={"pages": "21 p.", "publisher": "s.n."}))
        assert not attests_publication(_sp(meta={"source_title": "Colloque de 2020"}))

    def test_champs_editoriaux_ignores_hors_hal(self):
        assert not attests_publication(_sp(source="openalex", biblio={"publisher": "HAL CCSD"}))


class TestArbitrateConference:
    def test_communication_hal_sans_attestation_ni_echo(self):
        sources = [_sp(), _sp(id=2, source="scanr"), _sp(id=3, source="openalex")]
        assert arbitrate_conference("conference_paper", sources) == "conference"

    def test_attestation_d_une_autre_source(self):
        sources = [_sp(), _sp(id=2, source="openalex", doi="10.1109/icra.2021.1")]
        assert arbitrate_conference("conference_paper", sources) == "conference_paper"

    def test_resume_designe_par_une_source_l_emporte(self):
        sources = [
            _sp(source="crossref", doc_type="preprint", doi="10.5194/egusphere-egu21-8391"),
            _sp(id=2, source="openalex", doc_type="conference"),
        ]
        assert arbitrate_conference("preprint", sources) == "conference"

    def test_resume_en_supplement_de_revue(self):
        sources = [
            _sp(source="crossref", doc_type="article", journal_id=7, doi="10.1182/blood-2020"),
            _sp(id=2, source="wos", doc_type="conference", journal_id=7),
        ]
        assert arbitrate_conference("article", sources) == "conference"

    def test_recueil_de_resumes_hal(self):
        sources = [_sp(meta={"source_title": "Book of abstracts", "proceedings": True})]
        assert arbitrate_conference("conference_paper", sources) == "conference"

    def test_autres_types_inchanges(self):
        sources = [
            _sp(doc_type="book_chapter"),
            _sp(id=2, source="openalex", doc_type="conference"),
        ]
        assert arbitrate_conference("book_chapter", sources) == "book_chapter"
