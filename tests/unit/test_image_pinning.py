"""Toute image de base est désignée par son empreinte, et son emplacement est suivi.

Une étiquette (`python:3.12-slim`) se redéplace sur un autre contenu : deux constructions à deux moments partent d'images différentes sans que rien ne le dise. L'empreinte désigne l'image qui a été examinée.

Chaque répertoire portant une description de construction figure dans la configuration du robot de mise à jour, qui propose la montée des empreintes qu'il y trouve.
"""

import re

import yaml

from infrastructure import PROJECT_ROOT

_DEPENDABOT = PROJECT_ROOT / ".github" / "dependabot.yml"
_FROM = re.compile(r"^FROM\s+(\S+)", re.M)
_EMPREINTE = re.compile(r"@sha256:[0-9a-f]{64}$")


def _descriptions_de_construction() -> list[tuple[str, str]]:
    """Chemins des descriptions de construction du dépôt, et leur contenu."""
    chemins = [PROJECT_ROOT / "Dockerfile", *PROJECT_ROOT.glob("interfaces/*/Dockerfile")]
    return [
        (chemin.relative_to(PROJECT_ROOT).as_posix(), chemin.read_text(encoding="utf-8"))
        for chemin in chemins
        if chemin.is_file()
    ]


def test_le_depot_porte_des_descriptions_de_construction():
    """Garde-fou du parcours : un chemin fautif rendrait les assertions suivantes vides, donc vertes."""
    assert len(_descriptions_de_construction()) >= 3


def test_chaque_image_de_base_porte_son_empreinte():
    non_epinglees = [
        (chemin, image)
        for chemin, contenu in _descriptions_de_construction()
        for image in _FROM.findall(contenu)
        if not _EMPREINTE.search(image)
    ]
    assert not non_epinglees, (
        f"Images de base désignées par étiquette seule : {non_epinglees}. Une étiquette se "
        "redéplace sur un autre contenu ; y joindre l'empreinte de l'image examinée "
        "(`image:tag@sha256:…`)."
    )


def test_chaque_description_de_construction_est_suivie_par_le_robot():
    """Un répertoire portant une description de construction figure dans la configuration du robot de mise à jour."""
    config = yaml.safe_load(_DEPENDABOT.read_text(encoding="utf-8"))
    suivis = {
        entree["directory"].rstrip("/") or "/"
        for entree in config["updates"]
        if entree["package-ecosystem"] == "docker"
    }
    repertoires = {
        "/" + chemin.rsplit("/", 1)[0] if "/" in chemin else "/"
        for chemin, _ in _descriptions_de_construction()
    }
    manquants = repertoires - suivis
    assert not manquants, (
        f"Répertoires portant une description de construction hors du suivi : {sorted(manquants)}. "
        "Une empreinte se fige : sans suivi, elle vieillit sur place. Ajouter une entrée "
        "`docker` pour chacun dans `.github/dependabot.yml`."
    )
