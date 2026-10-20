"""Value object `PersonNameForm` + factory `compute_person_name_forms`.

Une forme de nom est une chaîne « prénom nom » normalisée, destinée au matching. Elle a le format de `contributor_information.author_name_normalized` : une forme de personne se compare telle quelle aux informations du contributeur d'une contribution source.

Du point de vue domain, une forme de nom est entièrement définie par sa string normalisée — VO immuable, égalité par valeur.

Note storage : la table `person_name_forms (name_form, person_id, sources[])` est un **index inverse** dénormalisé pour le matching nom → personnes. Avec une PK composite `(name_form, person_id)`, « ajouter une source », « retirer une source » et « forme ambiguë » s'écrivent en SQL direct : écritures dans `infrastructure/repositories/person_repository/_name_forms.py`, lectures du matching dans la phase `persons`.
"""

from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import clean_raw_author_name, normalize_text
from domain.persons.name_matching import normalize_first_name


@dataclass(frozen=True)
class PersonNameForm:
    """Forme normalisée du nom d'une personne (VO).

    Clé : la chaîne normalisée. La normalisation préalable est portée par `compute_person_name_forms` ; le VO se contente de garantir la non-vacuité.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValidationError("PersonNameForm ne peut pas être vide")

    def __str__(self) -> str:
        return self.value


def name_form(last_name: str, first_name: str | None) -> str:
    """Forme « prénom nom » d'un nom et d'un prénom normalisés, parties vides omises. Même calcul que `contributor_information.author_name_normalized`."""
    return " ".join(part for part in (first_name, last_name) if part)


def contributor_name_forms(last_name: str, first_name: str | None) -> tuple[str, ...]:
    """Formes cherchées pour une contribution source de nom et prénom normalisés : « prénom nom », puis « nom prénom » pour une contribution source au nom et prénom inversés."""
    forms = (name_form(last_name, first_name), name_form(first_name or "", last_name))
    return tuple(dict.fromkeys(form for form in forms if form))


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Formes de nom d'une personne : « prénom nom » et « initiales nom », initiales séparées (« j m dupont »). Sans prénom, le nom seul.

    Le prénom est normalisé comme celui des contributions sources (`normalize_first_name`).
    """
    # Même nettoyage que les contributions sources : une fiche créée d'après une forme d'autorité contient l'année de naissance (« Philippe 1973- »).
    ln = normalize_text(clean_raw_author_name(last_name))
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
