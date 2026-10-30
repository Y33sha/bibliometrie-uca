"""Toute image de base est désignée par son empreinte, et son emplacement est suivi.

Une étiquette (`python:3.12-slim`) peut désigner un autre contenu d'une construction à l'autre ; l'empreinte désigne l'image examinée.

Chaque répertoire contenant une description de construction figure dans la configuration du robot de mise à jour. Le robot propose la montée des empreintes trouvées dans ces répertoires.

Toutes les déclarations de version de langage du dépôt s'accordent : les descriptions de construction, lues par l'intégration continue, et `.nvmrc`, qui fixe le Node du poste de développement. La version de uv suit la même règle.

Les conteneurs de service des workflows reprennent les images des compositions, suivies par le robot.
"""

import re

import yaml

from infrastructure import PROJECT_ROOT

_DEPENDABOT = PROJECT_ROOT / ".github" / "dependabot.yml"
_WORKFLOWS = sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml"))
_COMPOSITIONS = sorted(PROJECT_ROOT.glob("docker-compose*.yml"))
# Nom de l'image de base, et paramètre par lequel l'intégration continue installe l'outil.
_LANGAGES = {"python": "python-version", "node": "node-version", "ghcr.io/astral-sh/uv": "version"}
_EXPRESSION = re.compile(r"^\$\{\{.*\}\}$")
_NVMRC = PROJECT_ROOT / "interfaces" / "frontend" / ".nvmrc"
_FROM = re.compile(r"^FROM\s+(\S+)", re.M)
_EMPREINTE = re.compile(r"@sha256:[0-9a-f]{64}$")


def _descriptions_de_construction() -> list[tuple[str, str]]:
    """Renvoie les chemins des descriptions de construction du dépôt, et leur contenu."""
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
    """Un répertoire contenant une description de construction figure dans la configuration du robot de mise à jour."""
    config = yaml.safe_load(_DEPENDABOT.read_text(encoding="utf-8"))
    suivis = {
        chemin.rstrip("/") or "/"
        for entree in config["updates"]
        if entree["package-ecosystem"] == "docker"
        # Une entrée désigne un répertoire (`directory`) ou plusieurs (`directories`).
        for chemin in entree.get("directories") or [entree["directory"]]
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
    """Renvoie la version de chaque langage figée par les images de base."""
    versions: dict[str, set[str]] = {langage: set() for langage in _LANGAGES}
    for _, contenu in _descriptions_de_construction():
        for image in _FROM.findall(contenu):
            nom, _, etiquette = image.split("@", 1)[0].partition(":")
            if nom in versions:
                versions[nom].add(etiquette.split("-", 1)[0])
    return versions


def _versions_declarees_par_l_integration() -> dict[str, list[str]]:
    """Renvoie les versions de langage écrites en clair dans les workflows, par langage.

    Une valeur lue depuis les images est une expression `${{ … }}` ; toute autre est une version recopiée.
    """
    litterales: dict[str, list[str]] = {langage: [] for langage in _LANGAGES}
    for workflow in _WORKFLOWS:
        config = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job in config["jobs"].values():
            for step in job.get("steps", []):
                parametres = step.get("with") or {}
                for langage, cle in _LANGAGES.items():
                    valeur = str(parametres.get(cle, ""))
                    if valeur and not _EXPRESSION.match(valeur):
                        litterales[langage].append(f"{workflow.name} : {valeur}")
    return litterales


def _versions_declarees() -> dict[str, set[str]]:
    """Renvoie la version de chaque langage selon chaque déclaration du dépôt : images de base et `.nvmrc`.

    `nvm use` lit `.nvmrc` sans argument : les contrôles du frontend lancés avant un push s'exécutent sous ce Node.
    """
    versions = _versions_des_images()
    if _NVMRC.is_file():
        versions["node"].add(_NVMRC.read_text(encoding="utf-8").strip().lstrip("v"))
    return versions


def test_les_versions_de_langage_sont_reperees():
    """Garde-fou du parcours : un relevé vide rendrait l'accord suivant vrai sans rien vérifier."""
    versions = _versions_des_images()
    for langage in _LANGAGES:
        assert versions[langage], f"aucune image de base `{langage}` repérée"


def test_les_declarations_de_version_s_accordent():
    divergences = {
        langage: sorted(versions)
        for langage, versions in _versions_declarees().items()
        if len(versions) > 1
    }
    assert not divergences, (
        f"Versions de langage divergentes : {divergences}. Une montée portée sur une "
        "déclaration et pas sur les autres ferait construire deux images sur deux "
        "interpréteurs, ou exécuter les contrôles sous un troisième. Porter la montée sur "
        "toutes les descriptions de construction et sur `.nvmrc` à la fois."
    )


def test_l_integration_ne_redeclare_aucune_version():
    litterales = {
        langage: versions
        for langage, versions in _versions_declarees_par_l_integration().items()
        if versions
    }
    assert not litterales, (
        f"Versions de langage écrites en clair dans les workflows : {litterales}. Une valeur recopiée "
        "se désaccorde en silence de l'image qu'elle est censée refléter. Les installer depuis "
        "`./.github/actions/versions-de-langage`, qui les lit dans la description de construction."
    )


def _images_des_services() -> list[tuple[str, str]]:
    """Renvoie les images des conteneurs de service des workflows, avec le nom du workflow."""
    return [
        (workflow.name, service["image"])
        for workflow in _WORKFLOWS
        for job in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"].values()
        for service in (job.get("services") or {}).values()
    ]


def test_les_workflows_declarent_des_services():
    """Garde-fou du parcours : un relevé vide rendrait le test suivant vrai sans rien vérifier."""
    assert _images_des_services()


def test_les_services_des_workflows_reprennent_les_images_des_compositions():
    """Le robot suit les images des compositions, et ignore celles des workflows."""
    suivies = {
        service["image"]
        for composition in _COMPOSITIONS
        for service in yaml.safe_load(composition.read_text(encoding="utf-8"))["services"].values()
        if "image" in service
    }
    ecarts = [
        (workflow, image) for workflow, image in _images_des_services() if image not in suivies
    ]
    assert not ecarts, (
        f"Images de service absentes des compositions : {ecarts}. Le robot de mise à jour ne lit "
        "pas les workflows : reprendre l'image épinglée de `docker-compose.yml`, qu'il suit."
    )
