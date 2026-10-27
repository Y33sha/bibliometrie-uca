"""Règles métier pures spécifiques à la source HAL.

Interprétation des champs propres au schéma HAL — prédicats et fonctions de lecture qui encapsulent la connaissance de la sémantique HAL pour le reste du pipeline.
"""

import re

# Situation d'une publication vis-à-vis de HAL, du dépôt le plus complet au plus absent.
# `ok` : déposée dans la collection d'un laboratoire, et son texte y est accessible.
# `notice` : dans la collection, dépôt sans fichier — pas d'open access.
# `hors_collection` : présente dans HAL sans figurer dans cette collection.
# `hors_hal` : absente de HAL.
# Les trois premières se lisent au regard d'une collection ; seule la dernière s'en passe.
HAL_DEPOSIT_STATUSES: tuple[str, ...] = ("ok", "notice", "hors_collection", "hors_hal")

# Libellés d'affichage des statuts, partagés par la facette et l'export.
HAL_DEPOSIT_STATUS_LABELS: dict[str, str] = {
    "ok": "Texte",
    "notice": "Notice",
    "hors_collection": "Hors collection",
    "hors_hal": "Hors HAL",
}

# Code d'un domaine CCSD : des segments alphanumériques séparés par des points
# (`sdv`, `sdv.bbm.bm`), le tiret étant admis dans un segment (`info.info-oh`).
_DOMAIN_CODE = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")

# Annotation d'un libellé de domaine : `Informatique [cs]`, `Autre [cs.OH]`.
_DOMAIN_ANNOTATION = re.compile(r"\s*\[[^]]*\]")

# Libellés de feuilles fourre-tout du référentiel CCSD (`chim.othe`, `info.info-oh`,
# `spi.other`, `stat.ot`…). Ils rassembleraient sous un même concept des feuilles
# sans rapport, là où leur parent porte déjà le signal.
_GENERIC_DOMAIN_LABELS = frozenset({"autre", "autres"})


def hal_domain_labels(facet_entry: str) -> list[str]:
    """Libellés de chaque niveau d'un domaine, depuis une entrée de `fr_domainAllCodeLabel_fs`.

    L'entrée porte le code du domaine et le chemin de ses libellés, de la racine à la feuille : `sdv.bbm.bm_FacetSep_Sciences du Vivant [q-bio]/Biochimie, Biologie Moléculaire/Biologie moléculaire` donne `["Sciences du Vivant", "Biochimie, Biologie Moléculaire", "Biologie moléculaire"]`.

    La profondeur se lit du code et borne le découpage du chemin : le libellé de feuille peut lui-même contenir des `/` (« Chimie théorique et/ou physique », « Optique / photonique »), qu'un découpage libre romprait en libellés fantômes.

    Les annotations entre crochets sont retirées, et les libellés génériques écartés. Une entrée dont le code n'a pas la forme attendue ne donne aucun libellé : le référentiel en compte quelques-unes, où le code porte un chemin de libellés au lieu d'un code.
    """
    code, separator, path = facet_entry.partition("_FacetSep_")
    if not separator or not _DOMAIN_CODE.match(code):
        return []
    labels = []
    for segment in path.split("/", code.count(".")):
        label = _DOMAIN_ANNOTATION.sub("", segment).strip()
        if label and label.lower() not in _GENERIC_DOMAIN_LABELS:
            labels.append(label)
    return labels
