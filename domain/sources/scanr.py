"""Règles métier pures spécifiques à la source ScanR.

Interprétation des champs propres au schéma ScanR (élasticsearch
dataesr) — prédicats et extracteurs qui encapsulent la connaissance
de la sémantique ScanR pour le reste du pipeline.
"""


def derive_scanr_oa_status(is_oa: bool | None, oa_evidence: dict | None) -> str | None:
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
    surestimer dans les cas hybrid.

    TODO (chantier ultérieur) : exploiter `journals.oa_model` au moment
    du normalize pour distinguer gold de hybrid à la source plutôt que
    de s'en remettre à OpenAlex.
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
