"""Value object `Address` — adresse normalisée.

L'adresse en tant qu'objet métier est définie par son texte
normalisé : c'est sa clé naturelle, et deux adresses au même texte
normalisé sont la même adresse. VO immuable, égalité par valeur.

Le pendant « état de résolution » de l'adresse (rattachement à des
structures, statut de confirmation, pays détectés, date de
résolution) est porté par l'aggregate `AddressAffiliation` dans
`domain/addresses/affiliation.py`.
"""

from dataclasses import dataclass

from domain.errors import ValidationError


@dataclass(frozen=True)
class Address:
    """Adresse institutionnelle normalisée (VO).

    Identité = `normalized_text`. La normalisation préalable est
    portée par les normalizers du pipeline ; le VO se contente de
    garantir la non-vacuité.
    """

    normalized_text: str

    def __post_init__(self) -> None:
        if not self.normalized_text or not self.normalized_text.strip():
            raise ValidationError("Address.normalized_text ne peut pas être vide")

    def __str__(self) -> str:
        return self.normalized_text
