"""Formes de nom, pour le matching des personnes : chaînes « prénom nom » normalisées, comparables telles quelles à `contributor_information.author_name_normalized`."""

from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import clean_raw_author_name, normalize_text
from domain.persons.name_matching import normalize_first_name


@dataclass(frozen=True)
class PersonNameForm:
    """Forme de nom d'une personne, non vide."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValidationError("PersonNameForm ne peut pas être vide")

    def __str__(self) -> str:
        return self.value


def name_form(last_name: str, first_name: str | None) -> str:
    """Renvoie la forme « prénom nom » d'un nom et d'un prénom normalisés, parties vides omises."""
    return " ".join(part for part in (first_name, last_name) if part)


def contributor_name_forms(last_name: str, first_name: str | None) -> tuple[str, ...]:
    """Renvoie les formes cherchées pour une contribution source : « prénom nom », puis « nom prénom », pour une source qui inverse nom et prénom."""
    forms = (name_form(last_name, first_name), name_form(first_name or "", last_name))
    return tuple(dict.fromkeys(form for form in forms if form))


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Calcule les formes de nom d'une personne : « prénom nom » et « initiales nom », initiales séparées (« j m dupont »). Sans prénom, le nom seul.

    Le prénom est normalisé comme celui des contributions sources (`normalize_first_name`).
    """
    # Même nettoyage que les contributions sources : une fiche créée d'après une forme d'autorité contient l'année de naissance (« Philippe 1973- »).
    ln = normalize_text(clean_raw_author_name(last_name))
    fn = normalize_first_name(clean_raw_author_name(first_name))
    if not ln:
        return set()
    initials = " ".join(word[0] for word in fn.split())
    return {name_form(ln, fn), name_form(ln, initials)}


# Source, dans `person_name_forms.sources`, des formes calculées depuis le nom de la personne dans `persons`. Les autres sources sont celles du moissonnage (`hal`, `openalex`…).
CANONICAL_NAME_FORM_SOURCE = "persons"
