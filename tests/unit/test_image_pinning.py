"""Toute image de base est désignée par son empreinte, et son emplacement est suivi.

Une étiquette (`python:3.12-slim`) se redéplace sur un autre contenu : deux constructions à deux moments partent d'images différentes sans que rien ne le dise. L'empreinte désigne l'image qui a été examinée.

Chaque répertoire portant une description de construction figure dans la configuration du robot de mise à jour, qui propose la montée des empreintes qu'il y trouve.

Les descriptions de construction s'accordent sur une version de langage unique, et elles sont seules à la porter : l'intégration continue la lit chez elles, de sorte que les contrôles s'exécutent sur l'interpréteur qui est livré.
"""

import re

import yaml

from infrastructure import PROJECT_ROOT

_DEPENDABOT = PROJECT_ROOT / ".github" / "dependabot.yml"
_CI = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
# Nom de l'image de base, et paramètre par lequel l'intégration continue installe le langage.
_LANGAGES = {"python": "python-version", "node": "node-version"}
_EXPRESSION = re.compile(r"^\$\{\{.*\}\}$")
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


def _versions_des_images() -> dict[str, set[str]]:
    """Version de chaque langage telle que les images de base la figent."""
    versions: dict[str, set[str]] = {langage: set() for langage in _LANGAGES}
    for _, contenu in _descriptions_de_construction():
        for image in _FROM.findall(contenu):
            nom, _, etiquette = image.split("@", 1)[0].partition(":")
            if nom in versions:
                versions[nom].add(etiquette.split("-", 1)[0])
    return versions


def _versions_declarees_par_l_integration() -> dict[str, list[str]]:
    """Versions de langage écrites en clair dans l'intégration continue, par langage.

    Une valeur lue depuis les images est une expression `${{ … }}` ; toute autre est une version recopiée.
    """
    config = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    litterales: dict[str, list[str]] = {langage: [] for langage in _LANGAGES}
    for job in config["jobs"].values():
        for etape in job.get("steps", []):
            parametres = etape.get("with") or {}
            for langage, cle in _LANGAGES.items():
                valeur = str(parametres.get(cle, ""))
                if valeur and not _EXPRESSION.match(valeur):
                    litterales[langage].append(valeur)
    return litterales


def test_les_versions_de_langage_sont_reperees():
    """Garde-fou du parcours : un relevé vide rendrait l'accord suivant vrai sans rien vérifier."""
    versions = _versions_des_images()
    for langage in _LANGAGES:
        assert versions[langage], f"aucune image de base `{langage}` repérée"


def test_les_descriptions_de_construction_s_accordent_sur_la_version():
    divergences = {
        langage: sorted(versions)
        for langage, versions in _versions_des_images().items()
        if len(versions) > 1
    }
    assert not divergences, (
        f"Versions de langage divergentes entre descriptions de construction : {divergences}. "
        "Le robot de mise à jour ne lit qu'un répertoire à la fois et propose une montée par "
        "emplacement ; les accepter séparément ferait construire deux images sur deux "
        "interpréteurs. Porter la montée sur toutes les descriptions à la fois."
    )


def test_l_integration_ne_redeclare_aucune_version():
    litterales = {
        langage: versions
        for langage, versions in _versions_declarees_par_l_integration().items()
        if versions
    }
    assert not litterales, (
        f"Versions de langage écrites en clair dans `ci.yml` : {litterales}. Une valeur recopiée "
        "se désaccorde en silence de l'image qu'elle est censée refléter. Les installer depuis "
        "`./.github/actions/versions-de-langage`, qui les lit dans la description de construction."
    )
