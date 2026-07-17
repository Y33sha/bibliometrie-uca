"""Règles métier pures spécifiques à la source HAL.

Interprétation des champs propres au schéma HAL — prédicats et extracteurs qui encapsulent la connaissance de la sémantique HAL pour le reste du pipeline.
"""

import re
from datetime import date

# Code d'un domaine CCSD : des segments alphanumériques séparés par des points
# (`sdv`, `sdv.bbm.bm`), le tiret étant admis dans un segment (`info.info-oh`).
_DOMAIN_CODE = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")

# Annotation d'un libellé de domaine : `Informatique [cs]`, `Autre [cs.OH]`.
_DOMAIN_ANNOTATION = re.compile(r"\s*\[[^]]*\]")

# Libellés de feuilles fourre-tout du référentiel CCSD (`chim.othe`, `info.info-oh`,
# `spi.other`, `stat.ot`…). Ils rassembleraient sous un même concept des feuilles
# sans rapport, là où leur parent porte déjà le signal.
_GENERIC_DOMAIN_LABELS = frozenset({"autre", "autres"})

# Repositories ouverts reconnus par HAL via `linkExtId_s` qu'on traite
# comme green OA (= dépôt en archive ouverte).
#
# - `arxiv` : preprint server fondateur, contenu intégralement en libre
#   accès.
# - `pubmedcentral` (PMC) : repository biomédical archivant les articles
#   accessibles librement (NIH-mandate + dépôts volontaires). Le contenu
#   n'est pas uniformément sous licence OA (certains articles "free to
#   read" sans droits de réutilisation, embargos), mais la lecture est
#   ouverte → traité comme green (= accès lecture libre via repo).
#
# Ne sont PAS dans cette liste :
# - `openaccess` : lien vers DOI éditeur, statut réel gold/hybrid/
#   bronze indéterminable depuis HAL seul.
# - `istex` : plateforme CNRS d'accès aux contenus payants, l'inclusion
#   ne garantit pas l'OA réel (et empiriquement ces docs ont aussi un
#   fileMain_s, donc capturés en green par la règle file_main).
GREEN_LINK_EXT_IDS = frozenset({"arxiv", "pubmedcentral"})


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


def derive_hal_oa_status(
    open_access_bool: bool | None,
    file_main: str | None,
    link_ext_id: str | None,
    embargo_until: date | None = None,
) -> str | None:
    """Mapping HAL → enum oa_status canonique.

    `openAccess_bool=true` recouvre plusieurs réalités ; l'arbitrage se fait sur `fileMain_s`, `linkExtId_s` et l'embargo :
      - file_main présent + embargo actif (`embargo_until` renseigné) → 'embargoed' (fichier déposé, accès légalement différé ; la levée à l'échéance est portée par une règle de correction `oa_status`, pas ici)
      - file_main présent → 'green' (dépôt effectif en HAL)
      - link_ext_id ∈ GREEN_LINK_EXT_IDS (arxiv, pubmedcentral) → 'green'
      - link_ext_id == 'openaccess' → 'hybrid' (lien vers le DOI éditeur, voie non nuancée ; défaut conservatif, arbitré vers 'gold' en aval par `best_oa_status` si une autre source le confirme)
      - open_access_bool=False → 'closed'
      - open_access_bool=True sans autre signal (istex, etc.) → None (délégation à OpenAlex/Unpaywall)
      - open_access_bool=None → None
    """
    if file_main and embargo_until is not None:
        return "embargoed"
    if file_main:
        return "green"
    if link_ext_id in GREEN_LINK_EXT_IDS:
        return "green"
    if link_ext_id == "openaccess":
        return "hybrid"
    if open_access_bool is None:
        return None
    if not open_access_bool:
        return "closed"
    return None
