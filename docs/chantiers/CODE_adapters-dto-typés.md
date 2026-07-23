# Conversion des adapters de lecture vers des DTO typés

## Contexte

Plusieurs adapters de lecture API (`infrastructure/queries/api/`) suivent un pattern hérité de Pydantic v2 : les fonctions libres construisent des `dict[str, Any]` (ou `list[dict[...]]`), et la conversion vers les DTO du port (`application/ports/api/`) se fait à la sortie de l'adapter, par `Modele.model_validate(dict)` ou `Modele(**dict)`.

Le pattern cible, déjà appliqué au package `persons` : chaque fonction libre **construit et retourne directement le DTO typé** déclaré par le port ; l'adapter (`PgXxxQueries`) se contente de déléguer. Bénéfices : typage de bout en bout, mypy vérifie la construction champ par champ, suppression de l'indirection dict → validation, et la justification « dicts réutilisables hors API » tombe (rien ne les réutilise hors API).

À distinguer du `model_validate` qui **parse une valeur JSONB** (sortie de `json_agg`) en DTO : celui-là est un usage légitime et reste en place (`addresses`, `feedback`, `hal_problems`, `structures`).

## Décisions

- Cible : les fonctions libres retournent les DTO du port ; l'adapter délègue sans conversion.
- Avant chaque conversion, vérifier au cas par cas qu'aucun appelant hors adapter ne dépend de la forme dict.
- Les tests au niveau query passent de l'accès par clé (`res["x"]`) à l'accès par attribut (`res.x`) ; les tests API (JSON) restent inchangés.
- Passe dédiée, menée d'un bloc, séparée de la relecture de lisibilité.

## Phasage

- [x] `persons` — référence (list, identifiers, facets, detail, admin).
- [ ] `publications` — `list.py` (`list_publications`), `facets.py` (`_facet_*`, `publications_facets`, `publications_entity_facet`), `detail.py` (`get_publication_detail` et ses fetchs). L'adapter `__init__.py` retire ses `model_validate` et le `EntityFacetItem(**r)`. `duplicates.py` est déjà typé.
- [ ] `stats` — `collaborations.py`, `entity_facets.py`, `pivot.py` ; l'adapter `__init__.py` retire son `model_validate`.
- [ ] `journals` — `_journal_list_fields` / `_journal_detail_fields` renvoient des dicts de champs consommés par la construction des DTO ; les faire construire les DTO directement (cas plus léger).

## Questions ouvertes

- Confirmer par lecture qu'aucune fonction dict n'est réutilisée hors de son adapter avant de la convertir.
