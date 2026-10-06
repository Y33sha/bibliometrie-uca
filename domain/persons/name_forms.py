"""Value object `PersonNameForm` + factory `compute_person_name_forms`.

Une forme de nom est une représentation normalisée d'une combinaison (last_name, first_name) destinée au matching. Plusieurs formes par personne : « prenom nom », « nom prenom », formes initialisées, etc. (cf. `compute_person_name_forms` ci-dessous).

Du point de vue domain, une forme de nom est entièrement définie par sa string normalisée — VO immuable, égalité par valeur.

Note storage : la table `person_name_forms (name_form, person_id, sources[])` est un **index inverse** dénormalisé pour le matching nom → personnes. Les opérations d'écriture / interrogation sur ce mapping vivent côté repo (`infrastructure/repositories/person_repository/_name_forms.py`) : avec une PK composite `(name_form, person_id)` la sémantique "ajouter une source", "retirer une source", "forme ambiguë" devient SQL direct, sans représentation in-memory.
"""

from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import clean_raw_author_name, normalize_name


@dataclass(frozen=True)
class PersonNameForm:
    """Forme normalisée du nom d'une personne (VO).

    Identité = la string normalisée. La normalisation préalable est portée par `compute_person_name_forms` ; le VO se contente de garantir la non-vacuité.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValidationError("PersonNameForm ne peut pas être vide")

    def __str__(self) -> str:
        return self.value


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Calcule les variantes normalisées de formes de nom pour une personne.

    Règle de composition du domaine (ne dépend d'aucune BD). Les strings retournées sont les valeurs canoniques d'instances de `PersonNameForm`.

    Retourne un ensemble de formes normalisées :
      - "prenom nom", "nom prenom"
      - "initiale(s) nom", "nom initiale(s)"
        Si le prénom a plusieurs mots (ex: "jean michel"), produit :
        - initiales séparées : "j m nom", "nom j m"
        - initiales collées  : "jm nom", "nom jm"
    """
    return set(person_name_form_splits(last_name, first_name))


def person_name_form_splits(last_name: str, first_name: str) -> dict[str, tuple[str, str | None]]:
    """Formes de nom d'une personne (`compute_person_name_forms`), chacune avec son découpage (nom, prénom) normalisé. Le prénom d'une forme initialisée est fait d'initiales séparées (« j m »)."""
    # Même nettoyage que les signatures : une fiche créée d'après une forme d'autorité porte l'année de naissance (« Philippe 1973- »).
    ln = normalize_name(clean_raw_author_name(last_name))
    fn = normalize_name(clean_raw_author_name(first_name))
    if not ln:
        return {}
    if not fn:
        return {ln: (ln, None)}

    initials_spaced = " ".join(p[0] for p in fn.split())
    initials_joined = initials_spaced.replace(" ", "")
    splits: dict[str, tuple[str, str | None]] = {}
    for first, split_first in (
        (fn, fn),
        (initials_spaced, initials_spaced),
        (initials_joined, initials_spaced),
    ):
        splits[f"{first} {ln}"] = (ln, split_first)
        splits[f"{ln} {first}"] = (ln, split_first)
    return splits


# Marqueur de provenance inscrit dans `person_name_forms.sources` pour les formes calculées
# par `compute_person_name_forms` depuis la table `persons`, par opposition aux formes attestées
# par une source d'extraction (`hal`, `openalex`…). Sa présence dans `sources` signale
# l'appartenance de la forme au nom canonique de la personne.
CANONICAL_NAME_FORM_SOURCE = "persons"
