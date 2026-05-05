"""Règles métier pures spécifiques à la source HAL.

Interprétation des champs propres au schéma HAL — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique HAL
pour le reste du pipeline.
"""


def derive_hal_oa_status(open_access_bool: bool | None) -> str | None:
    """Mapping `openAccess_bool` HAL → enum oa_status canonique.

    HAL n'expose qu'un signal binaire `openAccess_bool` qui signifie
    « un fichier est déposé et téléchargeable depuis l'archive HAL ».
    C'est exactement la définition canonique de green OA (= archivé en
    repository auteur), donc le mapping est direct.

    Sémantique :
      - True  → 'green'
      - False → 'closed'
      - None  → None (champ absent ; ne devrait pas arriver en pratique
        car l'extracteur HAL le demande systématiquement, mais on évite
        l'inférence implicite)

    Note : HAL ne connaît pas la voie OA chez l'éditeur (gold/hybrid/
    bronze). Si la pub a aussi des sources OpenAlex/Unpaywall avec une
    voie plus précise, `best_oa_status` arbitre côté
    `refresh_from_sources` (gold > hybrid > bronze > green > closed >
    unknown).
    """
    if open_access_bool is None:
        return None
    return "green" if open_access_bool else "closed"
