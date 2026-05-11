"""Règles métier pures spécifiques à la source ScanR.

Interprétation des champs propres au schéma ScanR (élasticsearch
dataesr) — prédicats et extracteurs qui encapsulent la connaissance
de la sémantique ScanR pour le reste du pipeline.

Les `dict[str, Any]` ici sont des payloads JSON bruts de l'API ScanR
(frontière dynamique avec une source externe, schéma non typé).
"""

from typing import Any


def select_leaf_affiliations(affiliations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtre les affiliations ScanR aux entrées marquées labo.

    ScanR renvoie côte à côte l'affiliation labo (champ
    ``id_name_author_labo`` rempli, c'est la seule affichée
    publiquement côté ScanR) et les pures tutelles, déjà dérivables
    via ``structures_parents``. Ne garder que la labo évite la
    double-comptabilisation des tutelles parentes en aval.

    Symétrique côté HAL de la préférence
    ``authIdHasPrimaryStructure_fs`` (labos feuilles) sur
    ``authIdHasStructure_fs`` (arbre aplati incluant les tutelles).

    Fallback sur la liste complète si aucune entrée n'est marquée labo
    (auteur non rattaché à un labo identifié côté ScanR) — sinon on
    perdrait toute affiliation pour cet auteur.
    """
    labo = [a for a in affiliations if a.get("id_name_author_labo")]
    return labo or affiliations


def extract_nnt_from_scanr_id(scanr_id: str | None) -> str | None:
    """Extrait le NNT d'un `scanr_id` quand celui-ci encode une thèse.

    ScanR encode les thèses sous la forme `these<NNT>` (ex.
    `these2021CLFAC030` → NNT `2021CLFAC030`). Tout autre format =
    pas une thèse, on retourne None.
    """
    if scanr_id and scanr_id.startswith("these"):
        return scanr_id[len("these") :].upper()
    return None


def derive_scanr_oa_status(is_oa: bool | None, oa_evidence: dict[str, Any] | None) -> str | None:
    """Mapping (isOa, oaEvidence) ScanR → enum oa_status canonique.

    ScanR n'expose pas de statut OA nuancé ; il faut l'inférer de
    `isOa` (bool) et de `oaEvidence.hostType` / `oaEvidence.license`.

    Sémantique :
      - is_oa=None → None (pas d'assertion ; on délègue aux autres
        sources via `best_oa_status` côté `refresh_from_sources`)
      - is_oa=False → 'closed' (assertion explicite : ni Unpaywall ni
        les signaux ScanR n'ont trouvé d'accès ouvert)
      - is_oa=True + hostType='repository' → 'green' (dépôt en archive
        ouverte, c'est exactement la définition canonique de green OA)
      - is_oa=True + hostType='publisher' + license cc-* → 'hybrid'
        (cf. note approximation ci-dessous)
      - is_oa=True + hostType='publisher' sans license cc-* → 'bronze'
        (accès libre chez l'éditeur sans licence ouverte explicite)
      - is_oa=True + hostType absent / inconnu → None (cas limite, on
        délègue)

    Approximation 'hybrid' : pour distinguer gold (journal full-OA) de
    hybrid (journal d'abonnement avec article ouvert), il faut savoir
    si la revue est full-OA — ScanR ne le dit pas. On choisit 'hybrid'
    comme valeur conservatrice : si le journal est en réalité full-OA,
    OpenAlex/Unpaywall remontera 'gold' et `best_oa_status` arbitre
    `gold > hybrid` côté `refresh_from_sources`, donc la valeur
    canonique sera correcte. À l'inverse, partir de 'gold' nous ferait
    surestimer dans les cas hybrid. Choix symétrique côté HAL pour
    `linkExtId_s='openaccess'`.

    TODO (chantier ultérieur) : quand on aura le lookup
    `journals.oa_model` au moment du normalize, on pourra remonter
    le défaut publisher de 'hybrid' à 'gold' (la voie la plus fréquente)
    et rétrograder à 'hybrid' uniquement quand le journal n'est pas
    full-OA. Même TODO côté HAL.
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
