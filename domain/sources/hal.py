"""Lecture des champs propres à HAL."""

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

# Code d'un domaine CCSD : des segments alphanumériques séparés par des points (`sdv.bbm.bm`), le tiret admis dans un segment (`info.info-oh`).
_DOMAIN_CODE = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")

# Annotation d'un libellé de domaine : `Informatique [cs]`, `Autre [cs.OH]`.
_DOMAIN_ANNOTATION = re.compile(r"\s*\[[^]]*\]")

# Libellés des feuilles fourre-tout du référentiel CCSD (`chim.othe`, `spi.other`…), qui réuniraient des feuilles sans rapport. Leur parent suffit.
_GENERIC_DOMAIN_LABELS = frozenset({"autre", "autres"})


def hal_domain_labels(facet_entry: str) -> list[str]:
    """Libellés de chaque niveau d'un domaine, depuis une entrée de `fr_domainAllCodeLabel_fs`.

    L'entrée contient le code du domaine et le chemin de ses libellés, de la racine à la feuille : `sdv.bbm.bm_FacetSep_Sciences du Vivant [q-bio]/Biochimie, Biologie Moléculaire/Biologie moléculaire` donne `["Sciences du Vivant", "Biochimie, Biologie Moléculaire", "Biologie moléculaire"]`.

    La profondeur du code borne le découpage du chemin : un libellé peut contenir des `/` (« Optique / photonique »).

    Les annotations entre crochets sont retirées, et les libellés génériques écartés. Une entrée dont le code n'a pas la forme attendue ne donne aucun libellé : dans quelques entrées du référentiel, un chemin de libellés tient lieu de code.
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
