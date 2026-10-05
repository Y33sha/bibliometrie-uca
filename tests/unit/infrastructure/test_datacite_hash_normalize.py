"""Empreinte de changement d'un nœud DataCite : indifférente à la route de lecture et aux compteurs, sensible à la notice."""

import copy

from infrastructure.pipeline.change_detection import change_detection_hash

# Forme rendue par la route de liste (`/dois?query=…`).
_LISTED = {
    "id": "10.57745/jg7xsq",
    "type": "dois",
    "attributes": {
        "doi": "10.57745/jg7xsq",
        "titles": [{"title": "Mesures de pluie"}],
        "creators": [{"name": "Dupont, Jean", "affiliation": ["Université Clermont Auvergne"]}],
        "publicationYear": 2026,
        "alternateIdentifiers": None,
        "created": "2026-01-07T14:57:05Z",
        "updated": "2026-08-31T19:41:48Z",
        "viewCount": 3,
        "viewsOverTime": [{"yearMonth": "2026-08", "total": 3}],
    },
    "relationships": {"client": {"data": {"id": "rdg.prod", "type": "clients"}}},
}


def _single() -> dict:
    """Le même DOI tel que le rend la route unitaire (`/dois/{doi}`), un mois plus tard."""
    node = copy.deepcopy(_LISTED)
    node["attributes"].update(
        {
            "alternateIdentifiers": [],
            "prefix": "10.57745",
            "suffix": "jg7xsq",
            "published": "2026",
            "xml": "PD94bWwg",
            "created": "2026-01-07T14:57:05.000Z",
            "updated": "2026-09-30T08:00:00.000Z",
            "viewCount": 12,
            "viewsOverTime": [{"yearMonth": "2026-09", "total": 9}],
        }
    )
    node["relationships"] = {
        "client": {"data": {"id": "rdg.prod", "type": "clients"}},
        "versions": {"data": []},
        "citations": {"data": []},
    }
    return node


def test_les_deux_routes_donnent_la_meme_empreinte():
    assert change_detection_hash("datacite", _LISTED) == change_detection_hash(
        "datacite", _single()
    )


def test_un_changement_de_notice_change_l_empreinte():
    retitled = copy.deepcopy(_LISTED)
    retitled["attributes"]["titles"] = [{"title": "Mesures de pluie, version corrigée"}]
    assert change_detection_hash("datacite", retitled) != change_detection_hash("datacite", _LISTED)


def test_un_isbn_ajoute_change_l_empreinte():
    """`alternateIdentifiers` vide est ignoré ; renseigné, il compte (la normalisation y cherche les ISBN)."""
    with_isbn = copy.deepcopy(_LISTED)
    with_isbn["attributes"]["alternateIdentifiers"] = [
        {"alternateIdentifier": "978-2-07-036822-8", "alternateIdentifierType": "ISBN"}
    ]
    assert change_detection_hash("datacite", with_isbn) != change_detection_hash(
        "datacite", _LISTED
    )
