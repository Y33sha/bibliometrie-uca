"""Règles métier pures spécifiques à la source HAL.

Interprétation des champs propres au schéma HAL — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique HAL
pour le reste du pipeline.
"""

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


def derive_hal_oa_status(
    open_access_bool: bool | None,
    file_main: str | None,
    link_ext_id: str | None,
) -> str | None:
    """Mapping HAL → enum oa_status canonique.

    HAL n'expose pas de statut OA nuancé. `openAccess_bool=true` peut
    couvrir plusieurs réalités selon ce que HAL connaît :

    1. **Dépôt effectif en HAL** → `fileMain_s` populé. Vrai green OA.
    2. **Lien vers repository ouvert** → `linkExtId_s` ∈ {arxiv,
       pubmedcentral}. Repos canoniques, traités comme green.
    3. **Lien éditeur ou plateforme par abonnement** → `linkExtId_s`
       ∈ {`openaccess` (DOI éditeur, gold/hybrid/bronze indéterminé),
       `istex` (plateforme par abonnement)}. HAL ne nuance pas la
       voie OA réelle, on renvoie `None` et le statut canonique sera
       déterminé par `best_oa_status` côté `refresh_from_sources` à
       partir des autres sources (OpenAlex/Unpaywall sait nuancer).

    Sémantique :
      - file_main présent → 'green' (fichier déposé en HAL)
      - link_ext_id ∈ GREEN_LINK_EXT_IDS → 'green' (arxiv aujourd'hui)
      - open_access=False → 'closed' (assertion explicite : ni dépôt
        HAL ni repo ouvert canonique)
      - open_access=True + lien ambigu → None (accès externe signalé
        mais voie OA réelle inconnue, on s'abstient pour laisser
        OpenAlex/Unpaywall décider via best_oa_status)
      - open_access=None → None (cas limite, pas d'assertion HAL)

    TODO (chantier ultérieur) : pour les liens éditeur (`openaccess`),
    si on récupère plus tard une licence depuis l'éditeur (DOI), on
    pourrait remonter hybrid/gold/bronze comme on le fait côté ScanR.
    """
    if file_main:
        return "green"
    if link_ext_id in GREEN_LINK_EXT_IDS:
        return "green"
    if open_access_bool is None:
        return None
    if not open_access_bool:
        return "closed"
    return None
