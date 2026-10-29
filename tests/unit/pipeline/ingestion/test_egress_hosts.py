"""Hôtes que le trafic sortant peut joindre.

La liste d'hôtes déclarée est celle des destinations joignables. Trois mécanismes la garantissent : un contrat d'architecture interdit au code qui sert les requêtes HTTP d'importer un client réseau ; le helper HTTP partagé suit seulement les redirections vers le même hôte (`test_http_retry`) ; ce module confronte les URL écrites dans le code à la liste.

La confrontation vise `pipeline/ingestion/`, d'où partent les requêtes. Les espaces de noms XML que les normaliseurs y lisent sont des identifiants, jamais appelés. Les URL des autres couches désignent des pages à afficher (une fiche HAL, un profil ORCID), jamais appelées non plus.
"""

import re
from pathlib import Path

import pytest

from infrastructure import PROJECT_ROOT
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.complements.doaj import ALLOWED_DUMP_HOSTS, DOAJ_CSV_DUMP_URL

HOTES_DECLARES = frozenset(
    {
        "api.archives-ouvertes.fr",
        "api.openalex.org",
        "api.clarivate.com",
        "api.crossref.org",
        "api.datacite.org",
        "api.unpaywall.org",
        "doaj.org",
        "doi.org",
        "theses.fr",
        "cluster-production.elasticsearch.dataesr.ovh",
        "www.sudoc.fr",
        "zenodo.org",
        # `doaj.org` redirige le téléchargement du dump DOAJ vers un lien signé sur son stockage objet : seule redirection vers un autre hôte que le code suive (`ALLOWED_DUMP_HOSTS`).
        "doaj-live-journal-csv.s3.amazonaws.com",
    }
)
"""Destinations joignables depuis la couche sortante. Y ajouter un hôte est un geste délibéré."""

_COUCHE_SORTANTE = PROJECT_ROOT / "pipeline" / "ingestion"
_URL = re.compile(r"https?://([A-Za-z0-9._-]+)")

_ESPACES_DE_NOMS_XML = frozenset({"www.tei-c.org", "www.w3.org"})
"""Hôtes des espaces de noms XML du TEI de HAL : des identifiants, jamais appelés."""

_IDENTIFIANTS = frozenset({"openalex.org"})
"""Hôtes des identifiants en forme d'URL (`https://openalex.org/W…`) que lit la normalisation : jamais appelés."""


def _hotes_ecrits_dans(racine: Path) -> set[str]:
    """Hôtes de toutes les URL littérales des modules Python d'une arborescence, hors espaces de noms XML et identifiants."""
    hotes: set[str] = set()
    for fichier in racine.rglob("*.py"):
        hotes |= set(_URL.findall(fichier.read_text(encoding="utf-8")))
    return hotes - _ESPACES_DE_NOMS_XML - _IDENTIFIANTS


class TestListeDeclaree:
    def test_chaque_url_de_base_vise_un_hote_declare(self):
        for source, url in API_BASE_URLS.items():
            hote = _URL.match(url)
            assert hote is not None, source
            assert hote.group(1) in HOTES_DECLARES, f"{source} → {hote.group(1)}"

    def test_le_referentiel_des_revues_vise_un_hote_declare(self):
        hote = _URL.match(DOAJ_CSV_DUMP_URL)
        assert hote is not None
        assert hote.group(1) in HOTES_DECLARES

    def test_la_redirection_admise_ne_sort_pas_de_la_liste(self):
        assert ALLOWED_DUMP_HOSTS <= HOTES_DECLARES


class TestAucuneUrlEcarte:
    def test_aucune_url_de_la_couche_sortante_ne_vise_un_hote_non_declare(self):
        """Une source ajoutée vers un hôte absent de la liste fait échouer le test."""
        inconnus = _hotes_ecrits_dans(_COUCHE_SORTANTE) - HOTES_DECLARES
        assert not inconnus, (
            f"Hôtes écrits dans la couche sortante sans figurer à la liste : {sorted(inconnus)}. "
            "Les y inscrire est un geste délibéré : la liste énumère les destinations joignables."
        )

    def test_la_liste_ne_porte_pas_d_hote_devenu_inutile(self):
        """Un hôte retiré du code sort de la liste : elle décrit seulement ce qui est joignable."""
        ecrits = _hotes_ecrits_dans(_COUCHE_SORTANTE) | set(ALLOWED_DUMP_HOSTS)
        assert HOTES_DECLARES <= ecrits, sorted(HOTES_DECLARES - ecrits)


@pytest.mark.parametrize("source", sorted(API_BASE_URLS))
def test_chaque_source_est_jointe_en_https(source: str):
    """Le chiffrement du transport ne dépend pas de la source interrogée."""
    assert API_BASE_URLS[source].startswith("https://")
