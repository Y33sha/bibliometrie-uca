"""Indicateurs de citation d'un enregistrement source, stockés dans `source_publications.impact`.

Chaque source renseigne les indicateurs qu'elle expose. Le nombre de citations vient de toutes les sources qui le comptent. Les indicateurs normalisés viennent d'OpenAlex : le FWCI (Field-Weighted Citation Impact, rapport entre les citations reçues et la moyenne mondiale des publications de même discipline, année et type) et le percentile de citations normalisé, avec ses seuils top 10 % et top 1 %.
"""

from dataclasses import dataclass, fields

from domain.types import JsonValue


@dataclass(frozen=True, slots=True, kw_only=True)
class Impact:
    cited_by_count: int | None = None
    fwci: float | None = None
    citation_percentile: float | None = None
    """Percentile de citations normalisé, entre 0 et 1."""
    top_10_percent: bool | None = None
    top_1_percent: bool | None = None

    def to_json(self) -> dict[str, JsonValue] | None:
        """Objet JSON des indicateurs renseignés, `None` si aucun ne l'est."""
        values: dict[str, JsonValue] = {
            f.name: value for f in fields(self) if (value := getattr(self, f.name)) is not None
        }
        return values or None
