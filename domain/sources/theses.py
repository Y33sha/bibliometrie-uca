"""Règles métier pures spécifiques à la source theses.fr.

Interprétation des champs propres au schéma theses.fr — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique theses.fr
pour le reste du pipeline.
"""

from domain.names import names_compatible
from domain.normalize import normalize_name


def thesis_authors_compatible(
    primary: tuple[str, str] | None,
    claimed: tuple[str, str],
) -> bool:
    """Indique si un auteur candidat est compatible avec l'auteur principal
    d'une thèse existante en BDD.

    Utilisée pour désambiguïser un match par titre+année : si la BDD a
    déjà une thèse avec ce titre cette année, vérifier que l'auteur
    qu'on tente d'attacher correspond bien.

    ``primary`` : ``(nom, prenom)`` de l'auteur principal en BDD (ou
    None si la thèse existante n'a pas d'auteur connu — typiquement
    lors d'une création tronquée). Pas encore normalisés.

    ``claimed`` : ``(nom_normalisé, prenom_normalisé)`` de l'auteur
    candidat (la forme normalisée vient du caller — déjà préparée
    avant lookup).

    Cascade :
      1. Pas d'auteur connu (``primary is None`` ou nom vide après
         normalisation) → accepte. Le titre+année font foi quand on
         n'a rien d'autre à comparer.
      2. ``names_compatible`` standard (ordre flexible nom/prénom +
         initiales).
      3. Fallback tokens identiques avec garde ``len >= 2`` : gère
         les particules type « Le », « Ben », « Da » que
         ``names_compatible`` peut rater quand elles atterrissent
         côté nom vs côté prénom selon les sources. Garde-fou
         minimal sur le nombre de tokens pour éviter qu'un simple
         prénom commun soit considéré « identique ».
    """
    if primary is None:
        return True
    ln = normalize_name(primary[0])
    fn = normalize_name(primary[1])
    if not ln:
        return True
    if names_compatible(claimed[0], claimed[1], ln, fn):
        return True
    tokens_a = set(f"{claimed[0]} {claimed[1]}".split())
    tokens_b = set(f"{ln} {fn}".split())
    return tokens_a == tokens_b and len(tokens_a) >= 2


def derive_theses_doc_type(date_soutenance: str | None) -> str:
    """Mapping date_soutenance → doc_type canonique pour theses.fr.

    theses.fr distribue à la fois les thèses soutenues et les thèses
    en préparation. La date de soutenance est le seul signal fiable
    pour distinguer les deux états :
      - dateSoutenance présent → 'thesis' (soutenue)
      - dateSoutenance absent → 'ongoing_thesis' (en cours)
    """
    return "thesis" if date_soutenance else "ongoing_thesis"


def extract_thesis_year(date_soutenance: str | None, date_inscription: str | None) -> int | None:
    """Année de référence d'une thèse : soutenance > première inscription.

    theses.fr fournit les deux dates au format `JJ/MM/AAAA`. La date de
    soutenance fait foi quand elle existe (thèse soutenue) ; sinon on
    se rabat sur la première inscription en doctorat (thèse en cours,
    encadrement encore actif). Renvoie None si les deux sont absents
    ou malformés.
    """
    for raw in (date_soutenance, date_inscription):
        if not raw:
            continue
        try:
            return int(raw.split("/")[-1])
        except (ValueError, IndexError):
            continue
    return None
