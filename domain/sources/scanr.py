"""Règles métier pures spécifiques à la source ScanR.

Interprétation des champs propres au schéma ScanR (élasticsearch dataesr) — prédicats et extracteurs qui encapsulent la connaissance de la sémantique ScanR pour le reste du pipeline.

Les `dict[str, Any]` ici sont des payloads JSON bruts de l'API ScanR (frontière dynamique avec une source externe, schéma non typé).
"""

from typing import Any


def select_leaf_affiliations(affiliations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtre les affiliations ScanR aux entrées marquées labo.

    ScanR renvoie côte à côte l'affiliation labo (champ `id_name_author_labo` rempli, c'est la seule affichée publiquement côté ScanR) et les pures tutelles, déjà dérivables via `structures_parents`. Ne garder que la labo évite la double-comptabilisation des tutelles parentes en aval.

    Symétrique côté HAL de la préférence `authIdHasPrimaryStructure_fs` (labos feuilles) sur `authIdHasStructure_fs` (arbre aplati incluant les tutelles).

    Fallback sur la liste complète si aucune entrée n'est marquée labo (auteur non rattaché à un labo identifié côté ScanR) — sinon on perdrait toute affiliation pour cet auteur.
    """
    labo = [a for a in affiliations if a.get("id_name_author_labo")]
    return labo or affiliations


def extract_nnt_from_scanr_id(scanr_id: str | None) -> str | None:
    """Extrait le NNT d'un `scanr_id` quand celui-ci encode une thèse.

    ScanR encode les thèses sous la forme `these<NNT>` (ex. `these2021CLFAC030` → NNT `2021CLFAC030`). Tout autre format = pas une thèse, on retourne None.
    """
    if scanr_id and scanr_id.startswith("these"):
        return scanr_id[len("these") :].upper()
    return None


# TODO: quand le lookup `journals.oa_model` sera disponible au normalize,
# remonter le défaut publisher de 'hybrid' à 'gold' (voie la plus fréquente)
# et ne rétrograder à 'hybrid' que pour les journaux non full-OA. Idem HAL.
def derive_scanr_oa_status(is_oa: bool | None, oa_evidence: dict[str, Any] | None) -> str | None:
    """Mapping (isOa, oaEvidence) ScanR → enum oa_status canonique.

    ScanR n'expose pas de statut OA nuancé ; il faut l'inférer de `isOa` (bool) et de `oaEvidence.hostType` / `oaEvidence.license` :
      - is_oa=None → None (pas d'assertion ; délégation aux autres sources via `best_oa_status`)
      - is_oa=False → 'closed' (assertion explicite : aucun accès ouvert trouvé)
      - is_oa=True + hostType='repository' → 'green' (dépôt en archive ouverte)
      - is_oa=True + hostType='publisher' + license cc-* → 'hybrid' (défaut conservatif, arbitré vers 'gold' en aval par `best_oa_status` si une autre source le confirme)
      - is_oa=True + hostType='publisher' sans license cc-* → 'bronze' (accès libre chez l'éditeur, licence ouverte non déclarée)
      - is_oa=True + hostType absent / inconnu → None (délégation)
    """
    if is_oa is None:
        return None
    if not is_oa:
        return "closed"
    ev = oa_evidence or {}
    host_type = ev.get("hostType")
    license_ = (ev.get("license") or "").lower()
    if host_type == "repository":
        return "green"
    if host_type == "publisher":
        return "hybrid" if license_.startswith("cc-") else "bronze"
    return None
