"""Règles métier pures spécifiques à la source HAL.

Interprétation des champs propres au schéma HAL — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique HAL
pour le reste du pipeline.
"""

from domain.source_publications.doc_types import map_doc_type


def derive_hal_doc_type(doc_type: str | None, sub_type: str | None) -> str:
    """Mapping HAL (docType_s, docSubType_s) → enum doc_type canonique.

    HAL est la seule source qui sépare type/sous-type. Cascade :
    1. Si sub_type présent, tente le mapping de la clé combinée
       `{doc_type}_{sub_type}` (ex. `ART_ARTREV` → `review`).
    2. Si la clé combinée ne mappe pas (résultat `'other'`), fallback
       sur le type seul (ex. `ART` → `article`).

    La table de mapping HAL dans `domain/doc_types._SOURCE_MAPS["hal"]`
    contient les deux formats — cette fonction encode la cascade de
    tentatives.

    Conserve le défaut historique `'OTHER'` quand `doc_type` est None
    pour compatibilité avec le call site (HAL renvoie rarement un
    docType_s vide, mais on évite l'erreur silencieuse).
    """
    raw = doc_type or "OTHER"
    if sub_type:
        result = map_doc_type(f"{raw}_{sub_type}", "hal")
        if result != "other":
            return result
    return map_doc_type(raw, "hal")


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
    3. **Lien éditeur** → `linkExtId_s='openaccess'` (lien vers le DOI
       éditeur). HAL atteste de l'OA chez l'éditeur mais ne nuance pas
       la voie (gold/hybrid/bronze). On renvoie 'hybrid' comme défaut
       conservatif — symétrique au choix ScanR pour `hostType=publisher`
       avec licence CC-*. Si le journal est en réalité full-OA, OpenAlex
       remontera 'gold' et `best_oa_status` arbitre `gold > hybrid` côté
       `refresh_from_sources`. À l'inverse, partir de 'gold' nous ferait
       surestimer dans les cas hybrid.
    4. **Plateforme par abonnement** → `linkExtId_s='istex'` (plateforme
       CNRS, accès institutionnel restreint). Pas vraiment OA. Empirique-
       ment ces docs ont aussi un `fileMain_s` (capturés en green par la
       règle ci-dessus) ; pour les rares cas sans fileMain on délègue
       (None) plutôt que de tagger faussement OA.

    Sémantique :
      - file_main présent → 'green'
      - link_ext_id ∈ GREEN_LINK_EXT_IDS (arxiv, pubmedcentral) → 'green'
      - link_ext_id == 'openaccess' → 'hybrid' (cf. note conservatif)
      - open_access=False → 'closed'
      - open_access=True + autre cas (istex, ou aucun signal additionnel)
        → None (délégation à OpenAlex/Unpaywall via best_oa_status)
      - open_access=None → None

    TODO (chantier ultérieur) : quand on aura le lookup `journals.oa_model`
    au moment du normalize, on pourra remonter le défaut publisher de
    'hybrid' à 'gold' (la voie la plus fréquente) et rétrograder à
    'hybrid' uniquement quand le journal n'est pas full-OA. Même TODO
    côté ScanR.
    """
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
