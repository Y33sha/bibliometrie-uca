"""Hôtes que le trafic sortant peut joindre.

Le dossier de sécurité énonce une liste d'hôtes et affirme qu'elle est celle des destinations effectivement joignables. Trois choses la tiennent : un contrat d'architecture interdit au code servant les requêtes HTTP d'atteindre un client réseau, le helper HTTP partagé traite une redirection comme une erreur (`test_http_retry`), et ce module confronte les URL écrites dans le code à la liste.

La confrontation porte sur `infrastructure/sources/`, couche d'où partent les requêtes. Les URL des autres couches désignent des pages à afficher — une fiche HAL, un profil ORCID — ou un espace de noms XML, et ne sont jamais appelées.
"""

import re
from pathlib import Path

import pytest

from infrastructure import PROJECT_ROOT
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.doaj.client import ALLOWED_DUMP_HOSTS, DOAJ_CSV_DUMP_URL

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
        # Le référentiel des revues en libre accès n'est pas servi par `doaj.org`, qui redirige
        # vers un lien signé sur son stockage objet. Seule redirection que le code suive, et
        # vers ce seul hôte (`ALLOWED_DUMP_HOSTS`).
        "doaj-live-journal-csv.s3.amazonaws.com",
    }
)
"""Destinations que le dossier de sécurité énumère. Y ajouter un hôte est un geste délibéré."""

_COUCHE_SORTANTE = PROJECT_ROOT / "infrastructure" / "sources"
_URL = re.compile(r"https?://([A-Za-z0-9._-]+)")


def _hotes_ecrits_dans(racine: Path) -> set[str]:
    """Hôtes de toutes les URL littérales des modules Python d'une arborescence."""
    hotes: set[str] = set()
    for fichier in racine.rglob("*.py"):
        hotes |= set(_URL.findall(fichier.read_text(encoding="utf-8")))
    return hotes


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
        """Une source ajoutée vers un hôte absent de la liste fait échouer l'intégration.

        C'est ce qui rend l'affirmation du dossier vérifiable plutôt que constatée à la lecture.
        """
        inconnus = _hotes_ecrits_dans(_COUCHE_SORTANTE) - HOTES_DECLARES
        assert not inconnus, (
            f"Hôtes écrits dans la couche sortante sans figurer à la liste : {sorted(inconnus)}. "
            "Les y inscrire suppose de mettre à jour le dossier de sécurité, qui les énumère."
        )

    def test_la_liste_ne_porte_pas_d_hote_devenu_inutile(self):
        """Un hôte retiré du code sort de la liste : elle décrit ce qui est joignable, non ce qui l'a été."""
        ecrits = _hotes_ecrits_dans(_COUCHE_SORTANTE) | set(ALLOWED_DUMP_HOSTS)
        assert HOTES_DECLARES <= ecrits, sorted(HOTES_DECLARES - ecrits)


@pytest.mark.parametrize("source", sorted(API_BASE_URLS))
def test_chaque_source_est_jointe_en_https(source: str):
    """Le chiffrement du transport ne dépend pas de la source interrogée."""
    assert API_BASE_URLS[source].startswith("https://")
