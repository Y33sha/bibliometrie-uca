"""Durcissement des conteneurs de production, tel que la description de déploiement le porte.

Le dossier de sécurité énonce cinq propriétés pour chaque service : exécution sous un compte non privilégié, refus de l'élévation de privilèges, abandon des capacités du noyau, racine en lecture seule, plafonds de ressources. Elles ne tiennent qu'à `docker-compose.prod.yml` : un service ajouté sans elles, ou un réglage retiré, ne se signale nulle part.

Ce module confronte l'énoncé au fichier, service par service, plutôt que de le laisser à la relecture.
"""

import re

import pytest
import yaml

from infrastructure import PROJECT_ROOT

_COMPOSE = PROJECT_ROOT / "docker-compose.prod.yml"
_DOCKERFILE = PROJECT_ROOT / "Dockerfile"

_PLAFONDS = ("mem_limit", "cpus", "pids_limit")
"""Clés bornant respectivement la mémoire, le temps processeur et le nombre de processus."""

_COMPTES_PRIVILEGIES = {"root", "0", "0:0"}

_USER = re.compile(r"^USER\s+(\S+)", re.M)
_UID = re.compile(r"--uid\s+(\d+)")


def _services() -> dict[str, dict]:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]


def _noms() -> list[str]:
    return sorted(_services())


@pytest.mark.parametrize("service", _noms())
def test_le_service_refuse_l_elevation_de_privileges(service: str) -> None:
    options = _services()[service].get("security_opt", [])
    assert "no-new-privileges:true" in options, (
        f"Le service `{service}` ne pose pas `no-new-privileges`. Un binaire portant le bit "
        "setuid y regagnerait des droits que le compte d'exécution n'a pas."
    )


@pytest.mark.parametrize("service", _noms())
def test_le_service_abandonne_les_capacites_du_noyau(service: str) -> None:
    assert _services()[service].get("cap_drop") == ["ALL"], (
        f"Le service `{service}` garde des capacités du noyau. Aucun des services n'en a "
        "l'usage : ils écoutent au-dessus du port 1024 et écrivent sur la sortie standard."
    )


@pytest.mark.parametrize("service", _noms())
def test_le_service_a_une_racine_en_lecture_seule(service: str) -> None:
    assert _services()[service].get("read_only") is True, (
        f"La racine du service `{service}` est inscriptible. Du code qui parviendrait à s'y "
        "exécuter y laisserait quelque chose derrière lui."
    )


@pytest.mark.parametrize("service", _noms())
def test_le_service_borne_ses_ressources(service: str) -> None:
    declaration = _services()[service]
    manquants = [cle for cle in _PLAFONDS if declaration.get(cle) is None]
    assert not manquants, (
        f"Le service `{service}` ne borne pas {', '.join(manquants)}. Une requête coûteuse, une "
        "boucle emballée ou un afflux d'appels atteindraient la machine hôte."
    )


@pytest.mark.parametrize("service", _noms())
def test_le_service_ne_s_execute_pas_en_root(service: str) -> None:
    """Un service nomme son compte, ou hérite de celui que son image déclare — jamais `root`."""
    compte = str(_services()[service].get("user", "")).strip()
    assert compte not in _COMPTES_PRIVILEGIES, (
        f"Le service `{service}` s'exécute sous un compte privilégié (`{compte}`)."
    )


def test_l_image_de_production_bascule_sur_un_compte_non_privilegie() -> None:
    """Les services construits ici ne nomment pas leur compte : ils tiennent celui de l'image."""
    description = _DOCKERFILE.read_text(encoding="utf-8")
    comptes = _USER.findall(description)
    assert comptes, "L'image de production reste sous `root` : aucune directive `USER`."
    assert comptes[-1] not in _COMPTES_PRIVILEGIES, (
        f"L'image de production s'achève sous `{comptes[-1]}`."
    )
    assert _UID.search(description), (
        "Le compte d'exécution de l'image n'a pas d'identifiant fixé. Un volume monté sur un "
        "chemin de l'image appartiendrait à un identifiant qui varie d'une construction à l'autre."
    )
