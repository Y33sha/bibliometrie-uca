"""Value object `PersonNameForm` + factory `compute_person_name_forms`.

Une forme de nom est une chaîne « prénom nom » normalisée, destinée au matching. Elle a le format de `author_identifying_keys.author_name_normalized` : une forme de personne se compare telle quelle à l'identité d'une signature.

Du point de vue domain, une forme de nom est entièrement définie par sa string normalisée — VO immuable, égalité par valeur.

Note storage : la table `person_name_forms (name_form, person_id, sources[])` est un **index inverse** dénormalisé pour le matching nom → personnes. Les opérations d'écriture / interrogation sur ce mapping vivent côté repo (`infrastructure/repositories/person_repository/_name_forms.py`) : avec une PK composite `(name_form, person_id)` la sémantique "ajouter une source", "retirer une source", "forme ambiguë" devient SQL direct, sans représentation in-memory.
"""

from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import clean_raw_author_name, normalize_name
from domain.persons.name_matching import normalize_first_name


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


def name_form(last_name: str, first_name: str | None) -> str:
    """Forme « prénom nom » d'un nom et d'un prénom normalisés, parties vides omises. Même calcul que `author_identifying_keys.author_name_normalized`."""
    return " ".join(part for part in (first_name, last_name) if part)


def signature_name_forms(last_name: str, first_name: str | None) -> tuple[str, ...]:
    """Formes cherchées pour une signature de nom et prénom normalisés : « prénom nom », puis « nom prénom » pour une signature au nom et prénom inversés."""
    forms = (name_form(last_name, first_name), name_form(first_name or "", last_name))
    return tuple(dict.fromkeys(form for form in forms if form))


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Formes de nom d'une personne : « prénom nom » et « initiales nom », initiales séparées (« j m dupont »). Sans prénom, le nom seul.

    Le prénom est normalisé comme celui des signatures (`normalize_first_name`).
    """
    # Même nettoyage que les signatures : une fiche créée d'après une forme d'autorité porte l'année de naissance (« Philippe 1973- »).
    ln = normalize_name(clean_raw_author_name(last_name))
    fn = normalize_first_name(clean_raw_author_name(first_name))
    if not ln:
        return set()
    initials = " ".join(word[0] for word in fn.split())
    return {name_form(ln, fn), name_form(ln, initials)}


# Marqueur de provenance inscrit dans `person_name_forms.sources` pour les formes calculées
# par `compute_person_name_forms` depuis la table `persons`, par opposition aux formes attestées
# par une source d'extraction (`hal`, `openalex`…). Sa présence dans `sources` signale
# l'appartenance de la forme au nom canonique de la personne.
CANONICAL_NAME_FORM_SOURCE = "persons"
