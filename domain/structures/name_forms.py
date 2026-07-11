"""Value object `StructureNameForm` — forme du nom d'une structure.

Contrairement à `PersonNameForm`, une forme de nom de structure n'est
pas qu'une string : elle est qualifiée par des options de matching
(`is_word_boundary` pour exiger une frontière de mot,
`is_excluding` pour les formes qui doivent provoquer un *rejet* du
match plutôt qu'un match, `requires_context_of` pour les formes qui
ne valident le match que si certaines autres structures sont aussi
présentes dans la même adresse).

Toutes ces attributs étant des valeurs (booléens, tuple d'entiers), la
classe reste un VO : égalité par contenu, immuable.
"""

from dataclasses import dataclass, field

from domain.errors import ValidationError


@dataclass(frozen=True)
class StructureNameForm:
    """Forme du nom d'une structure, avec options de matching (VO).

    Champs (miroir de la table `structure_name_forms`) :

    - `form_text` : la string à matcher (déjà normalisée).
    - `is_word_boundary` : exige une frontière de mot avant/après la
      forme pour valider un match (évite p. ex. de matcher « ica »
      dans « africa »).
    - `is_excluding` : si la forme matche, le match global est rejeté
      (forme négative).
    - `requires_context_of` : tuple d'ids de structures qui doivent
      aussi être présentes pour valider ce match (désambiguïsation).
    """

    form_text: str
    is_word_boundary: bool = False
    is_excluding: bool = False
    requires_context_of: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.form_text or not self.form_text.strip():
            raise ValidationError("StructureNameForm.form_text ne peut pas être vide")

    def __str__(self) -> str:
        return self.form_text


# En dessous de ce seuil (caractères, sur le texte normalisé), une forme doit exiger une
# frontière de mot : matchée en sous-chaîne, une forme courte produit trop de faux positifs
# (« ica » dans « africa »). L'invariant « forme courte ⇒ is_word_boundary » est verrouillé
# par une contrainte CHECK sur `structure_name_forms`, appliquée à l'écriture.
SHORT_FORM_MAX_LENGTH = 6


def is_short_form(form_text: str) -> bool:
    """Vrai si une forme de ce texte normalisé doit exiger une frontière de mot."""
    return len(form_text) <= SHORT_FORM_MAX_LENGTH
