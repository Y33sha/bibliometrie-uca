"""Value object `PersonNameForm` + factory `compute_person_name_forms`.

Une forme de nom est une représentation normalisée d'une combinaison
(last_name, first_name) destinée au matching. Plusieurs formes par
personne : « prenom nom », « nom prenom », formes initialisées, etc.
(cf. `compute_person_name_forms` ci-dessous).

Du point de vue domain, une forme de nom est entièrement définie par
sa string normalisée — VO immuable, égalité par valeur.

Note storage : la table `person_name_forms (name_form, person_id,
sources[])` est un **index inverse** dénormalisé pour le matching nom
→ personnes. Les opérations d'écriture / interrogation sur ce mapping
vivent côté repo (`infrastructure/repositories/person_repository/
_name_forms.py`) : avec une PK composite `(name_form, person_id)` la
sémantique "ajouter une source", "retirer une source", "forme
ambiguë" devient SQL direct, sans représentation in-memory.
"""

from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import normalize_name


@dataclass(frozen=True)
class PersonNameForm:
    """Forme normalisée du nom d'une personne (VO).

    Identité = la string normalisée. La normalisation préalable est
    portée par `compute_person_name_forms` ; le VO se contente de
    garantir la non-vacuité.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValidationError("PersonNameForm ne peut pas être vide")

    def __str__(self) -> str:
        return self.value


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Calcule les variantes normalisées de formes de nom pour une personne.

    Règle de composition du domaine (ne dépend d'aucune BD). Les
    strings retournées sont les valeurs canoniques d'instances de
    `PersonNameForm`.

    Retourne un ensemble de formes normalisées :
      - "prenom nom", "nom prenom"
      - "initiale(s) nom", "nom initiale(s)"
        Si le prénom a plusieurs mots (ex: "jean michel"), produit :
        - initiales séparées : "j m nom", "nom j m"
        - initiales collées  : "jm nom", "nom jm"
    """
    ln = normalize_name(last_name)
    fn = normalize_name(first_name)
    if not ln:
        return set()

    forms: set[str] = set()
    if fn:
        forms.add(f"{fn} {ln}")
        forms.add(f"{ln} {fn}")

        parts = fn.split()
        if parts:
            initials_spaced = " ".join(p[0] for p in parts)
            initials_joined = "".join(p[0] for p in parts)
            forms.add(f"{initials_spaced} {ln}")
            forms.add(f"{ln} {initials_spaced}")
            if initials_joined != initials_spaced:
                forms.add(f"{initials_joined} {ln}")
                forms.add(f"{ln} {initials_joined}")
    else:
        forms.add(ln)

    return forms
