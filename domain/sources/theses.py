"""Règles métier pures spécifiques à la source theses.fr.

Interprétation des champs propres au schéma theses.fr — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique theses.fr
pour le reste du pipeline.
"""


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
