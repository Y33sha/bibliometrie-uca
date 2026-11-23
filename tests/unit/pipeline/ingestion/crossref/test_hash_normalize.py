"""Empreinte de changement d'une œuvre Crossref : indifférente à la route de lecture et aux horodatages de Crossref, sensible au contenu de l'enregistrement source."""

import copy

from pipeline.ingestion.common.change_detection import change_detection_hash

# Forme renvoyée par la recherche par personne (`/works?filter=orcid:…`).
_SEARCHED = {
    "DOI": "10.1007/978-3-031-61712-6_7",
    "title": ["Modélisation des bâtiments"],
    "author": [{"given": "Jean", "family": "Dupont", "affiliation": []}],
    "subtitle": None,
    "relation": None,
    "is-referenced-by-count": 3,
    "score": 0.0,
    "created": {"date-time": "2024-07-23T12:31:08Z", "timestamp": 1721737868000},
    "deposited": {"date-time": "2024-07-23T12:37:32Z", "timestamp": 1721738252000},
    "indexed": {"date-time": "2025-03-25T16:46:15Z", "timestamp": 1742921175000},
}


def _single() -> dict:
    """Renvoie le même DOI, lu par la route unitaire (`/works/{doi}`) après une réindexation."""
    work = copy.deepcopy(_SEARCHED)
    work.update(
        {
            "subtitle": [],
            "relation": {},
            "score": 1,
            "created": {"date-time": "2024-07-23T08:31:08Z", "timestamp": 1721723468000},
            "indexed": {"date-time": "2026-11-15T22:30:00Z", "timestamp": 1794781800000},
        }
    )
    return work


def test_les_deux_routes_donnent_la_meme_empreinte():
    assert change_detection_hash("crossref", _SEARCHED) == change_detection_hash(
        "crossref", _single()
    )


def test_une_relation_ajoutee_change_l_empreinte():
    related = copy.deepcopy(_SEARCHED)
    related["relation"] = {"is-part-of": [{"id-type": "doi", "id": "10.1007/978-3-031-61712-6"}]}
    assert change_detection_hash("crossref", related) != change_detection_hash(
        "crossref", _SEARCHED
    )


def test_une_citation_nouvelle_change_l_empreinte():
    """Le nombre de citations, lu par la normalisation, reste dans l'empreinte."""
    cited = copy.deepcopy(_SEARCHED)
    cited["is-referenced-by-count"] = 4
    assert change_detection_hash("crossref", cited) != change_detection_hash("crossref", _SEARCHED)
