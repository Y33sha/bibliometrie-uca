"""Value object `PersonNameForm` — forme normalisée du nom d'une personne.

Une forme de nom est une représentation normalisée d'une combinaison
(last_name, first_name) destinée au matching. Voir
`domain/names.py:compute_person_name_forms` pour la règle de génération
(plusieurs formes par personne : « prenom nom », « nom prenom »,
formes initialisées, etc.).

Du point de vue domain, une forme de nom est entièrement définie par
sa string normalisée — VO immuable, égalité par valeur.

Note storage : la table `person_name_forms` (`name_form text +
person_ids int[] + sources text[]`) est un **index inverse**
dénormalisé pour le matching nom → personnes, pas un aggregate. Le VO
ne porte que la string ; la mapping `form → persons` est exposée par
les query services côté infrastructure.
"""

from dataclasses import dataclass

from domain.errors import ValidationError


@dataclass(frozen=True)
class PersonNameForm:
    """Forme normalisée du nom d'une personne (VO).

    Identité = la string normalisée. La normalisation préalable est
    portée par `domain/names.py:compute_person_name_forms` ; le VO se
    contente de garantir la non-vacuité.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValidationError("PersonNameForm ne peut pas être vide")

    def __str__(self) -> str:
        return self.value
