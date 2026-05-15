# Chantier — DTOs application-level pour les query services

Stub. À instruire.

## Idée

Aujourd'hui les query services API (`infrastructure/db/queries/*` consommés par les routers FastAPI) retournent des `dict[str, Any]`. Les routers font ensuite `Model.model_validate(...)` pour fabriquer le `BaseModel` correspondant au `response_model` (option A retenue par `CODE_chasse-aux-any` Phase 2.4).

L'option C écartée à l'époque (vu chantier `CODE_chasse-aux-any.md`) consisterait à faire en sorte que les query services retournent directement des **DTOs typés** plutôt que des `dict[str, Any]`.

## Conséquences

- Déplacement des modèles Pydantic hors `interfaces/api/models.py` vers `application/` (probablement `application/dtos/` ou éclaté par feature).
- Les Protocols `application/ports/api/*` retournent ces DTOs au lieu de `dict[str, Any]`.
- Les adapters `infrastructure/db/queries/Pg*Queries` instancient ces DTOs côté infra.
- Les routers ne font plus de `model_validate` — ils propagent directement le DTO renvoyé par le query service.

## Bénéfice

- Typage fort de bout en bout (query service → router → réponse HTTP) sans `dict[str, Any]` intermédiaire.
- Suppression d'une bonne partie de l'override « `interfaces.api.models` + records DB » dans `pyproject.toml`.

## Coût

- Refactor structurel (déplacement de package, refonte de ~30 query services + adapters + routers).
- Question de placement : `application/dtos/` global vs colocation par feature (`application/persons/dtos.py`, etc.).
- Articulation avec `CODE_rich-domain-model` Phase 8 (entités riches vs DTOs de projection) : à clarifier.
