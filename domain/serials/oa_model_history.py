"""Modèle open access d'une revue l'année de parution d'une publication.

Une revue en open access intégral (`full_oa`, `diamond`) garde son modèle pour les publications parues depuis son passage à l'open access intégral. Avant ce passage, son modèle est `subscription`. L'année du passage vient d'OpenAlex, sinon du DOAJ. Une année de passage inconnue, ou une année de parution inconnue, donne un modèle inconnu.
"""

from dataclasses import dataclass

from domain.serials.serial import OaModel

_FULL_OA_MODELS = frozenset({OaModel.FULL_OA, OaModel.DIAMOND})


@dataclass(frozen=True, slots=True)
class OaModelHistory:
    """Modèle open access actuel d'une revue et données de son passage à l'open access intégral."""

    model: OaModel | None
    openalex_is_oa: bool | None
    """La revue est en open access intégral d'après OpenAlex. `None` : revue absente d'OpenAlex ou jamais cherchée."""
    openalex_flip_year: int | None
    """Année du passage à l'open access intégral d'après OpenAlex, `None` pour une revue née en open access intégral."""
    doaj_since_year: int | None
    """Année depuis laquelle la revue publie tout son contenu sous licence ouverte, déclarée au DOAJ."""

    def model_at(self, year: int | None) -> OaModel | None:
        """Renvoie le modèle open access de la revue l'année `year`."""
        if self.model not in _FULL_OA_MODELS:
            return self.model
        if self.openalex_is_oa:
            if self.openalex_flip_year is None:
                return self.model
            since: int | None = self.openalex_flip_year
        else:
            since = self.doaj_since_year
        if since is None or year is None:
            return None
        return self.model if year >= since else OaModel.SUBSCRIPTION


def doaj_year(value: str | None) -> int | None:
    """Renvoie l'année déclarée au DOAJ, `None` pour une valeur absente ou autre qu'une année."""
    if value is None or not (value.isascii() and value.isdigit() and len(value) == 4):
        return None
    return int(value)
