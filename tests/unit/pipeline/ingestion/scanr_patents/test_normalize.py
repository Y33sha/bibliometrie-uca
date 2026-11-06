"""Tests unitaires de `pipeline.ingestion.scanr_patents.normalize`.

Couvre le titre et sa langue, la date du premier dépôt, les numéros de publication et de demande, les champs propres aux brevets dans `source_extras` et la lecture des inventeurs. Sans base de données.
"""

from __future__ import annotations

from datetime import date

from domain.contributions.contribution_roles import ContributionRole
from domain.source_records.source_extras import SourceExtra
from pipeline.ingestion.scanr_patents.normalize import (
    build_inventor_records,
    get_publication_date,
    get_title,
    publication_number,
    scanr_patents_source_record,
)
from tests.helpers.normalize_doubles import identifier_values


def _family(**overrides):
    """Renvoie une famille ScanR minimale, modelée sur la famille 42635118."""
    family = {
        "id": "42635118",
        "applicationDate": "2010-03-02T00:00:00",
        "publicationDate": "2011-09-09T00:00:00",
        "grantedDate": "2019-01-16T00:00:00",
        "productionType": "patent",
        "title": {
            "fr": "Utilisation du riluzole",
            "en": "USE OF RILUZOLE",
            "default": "USE OF RILUZOLE",
        },
        "summary": {"fr": "Résumé.", "en": "Abstract.", "default": ""},
        "applicants": [
            {
                "name": "Université Clermont Auvergne",
                "type": "organisation",
                "country": "FR",
                "ids": [
                    {"id": "K4lR3", "type": "paysage"},
                    {"id": "K4lR3", "type": "id_paysage"},
                    {"id": "130028061", "type": "siren"},
                    {"id": "13002806100013", "type": "siret"},
                ],
            }
        ],
        "inventors": [
            {"name": "Eschalier Alain", "ids": [{"id": "idref074728946", "type": "idref"}]},
            {"name": "Busserolles Jerome"},
            {"name": "Eschalier Alain"},
        ],
        "cpc": {"groupe": [{"code": "A61K31/428", "label": "Riluzole"}]},
        "patents": [
            {
                "office": "FR",
                "applicationNumber": "1051491",
                "applicationDate": "2010-03-02T00:00:00",
                "publicationNumber": "2957077A1",
                "publicationDate": "2011-09-09T00:00:00",
                "isPriority": True,
                "isGranted": False,
                "ipType": "PI",
                "espacenetUrl": "https://worldwide.espacenet.com/patent/search/?q=pn%3D%22FR2957077A1%22",
            },
            {
                "office": "WO",
                "applicationNumber": "2011050432",
                "publicationNumber": "2011107710A1",
            },
            {
                "office": "CN",
                "applicationNumber": "201180012116",
                "publicationNumber": "102917701A ",
            },
        ],
    }
    return {**family, **overrides}


class TestExtractors:
    def test_titre_francais_d_abord(self):
        assert get_title(_family()) == ("Utilisation du riluzole", "fr")

    def test_titre_anglais_a_defaut(self):
        family = _family(title={"fr": "", "en": "USE", "default": "USE"})
        assert get_title(family) == ("USE", "en")

    def test_date_du_premier_depot(self):
        assert get_publication_date(_family()).value == date(2010, 3, 2)

    def test_numero_de_publication_sans_code_de_type(self):
        assert publication_number("WO", "2011107710A1") == "WO2011107710"
        assert publication_number("ES", "2660236T3") == "ES2660236"
        assert publication_number("SG", "11201701523VA ") == "SG11201701523V"
        assert publication_number("FR", "") is None


class TestSourceRecord:
    def test_numeros_de_publication_et_de_demande(self):
        record = scanr_patents_source_record(_family(), 1, "42635118")
        assert identifier_values(record) == {
            "patent_publication_number": ["CN102917701", "FR2957077", "WO2011107710"],
            "patent_application_number": ["CN201180012116", "FR1051491", "WO2011050432"],
        }

    def test_champs_communs(self):
        record = scanr_patents_source_record(_family(), 1, "42635118")
        assert (record.title, record.raw_language, record.abstract) == (
            "Utilisation du riluzole",
            "fr",
            "Résumé.",
        )
        assert record.raw_doc_type == "patent"

    def test_source_extras(self):
        extras = scanr_patents_source_record(_family(), 1, "42635118").source_extras
        assert extras[SourceExtra.PATENT_FIRST_PUBLICATION_DATE] == "2011-09-09"
        assert extras[SourceExtra.PATENT_GRANT_DATE] == "2019-01-16"
        assert extras[SourceExtra.CPC] == [{"code": "A61K31/428", "label": "Riluzole"}]
        assert extras[SourceExtra.PATENT_APPLICANTS] == [
            {
                "name": "Université Clermont Auvergne",
                "type": "organisation",
                "country": "FR",
                "ids": {"paysage": ["K4lR3"], "siren": ["130028061"]},
            }
        ]
        first = extras[SourceExtra.PATENT_APPLICATIONS][0]
        assert first["publication_number"] == "2957077A1"
        assert (first["application_date"], first["priority"]) == ("2010-03-02", True)

    def test_demande_sans_lien_espacenet(self):
        extras = scanr_patents_source_record(_family(), 1, "42635118").source_extras
        assert "espacenet_url" not in extras[SourceExtra.PATENT_APPLICATIONS][0]

    def test_code_cpc_sans_libelle(self):
        cpc = {"groupe": [{"code": "C12P21/04", "label": "non disponible"}]}
        extras = scanr_patents_source_record(_family(cpc=cpc), 1, "1").source_extras
        assert extras[SourceExtra.CPC] == [{"code": "C12P21/04", "label": None}]

    def test_famille_sans_delivrance(self):
        extras = scanr_patents_source_record(_family(grantedDate=None), 1, "1").source_extras
        assert SourceExtra.PATENT_GRANT_DATE not in extras


class TestInventors:
    def test_un_inventeur_repete_compte_une_fois_avec_son_idref(self):
        records = build_inventor_records({"inventors": _family()["inventors"]})
        assert [(r.position, r.name.raw, r.identifiers) for r in records] == [
            (1, "Eschalier Alain", {"idref": "074728946"}),
            (2, "Busserolles Jerome", None),
        ]
        assert all(r.roles == [ContributionRole.INVENTOR] for r in records)

    def test_graphies_d_un_meme_nom_reunies(self):
        inventors = [{"name": "Mathias Jean Denis"}, {"name": "Mathias Jean-Denis"}]
        assert len(build_inventor_records({"inventors": inventors})) == 1

    def test_deux_idref_sous_un_meme_nom_font_deux_inventeurs(self):
        inventors = [
            {"name": "Martin Pierre", "ids": [{"id": "idref000000019", "type": "idref"}]},
            {"name": "Martin Pierre", "ids": [{"id": "idref000000027", "type": "idref"}]},
        ]
        assert len(build_inventor_records({"inventors": inventors})) == 2
