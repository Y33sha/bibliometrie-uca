"""Règles métier pures spécifiques à la source HAL.

Interprétation des champs propres au schéma HAL — prédicats et extracteurs qui encapsulent la connaissance de la sémantique HAL pour le reste du pipeline.
"""

from datetime import date

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


# TODO: quand le lookup `journals.oa_model` sera disponible au normalize,
# remonter le défaut publisher de 'hybrid' à 'gold' (voie la plus fréquente)
# et ne rétrograder à 'hybrid' que pour les journaux non full-OA. Idem ScanR.
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
