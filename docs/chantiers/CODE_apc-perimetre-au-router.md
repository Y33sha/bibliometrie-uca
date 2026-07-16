# Périmètre APC : le résoudre dans l'adapter au lieu de le faire descendre du router

## Contexte

La catégorisation APC classe une publication comme « interne » quand au moins un de ses `apc_payments.budget_structure_id` appartient à un ensemble de structures. Cet ensemble est le périmètre `perimeter_persons` dans sa clôture transitive — l'établissement et tous ses laboratoires descendants — sans aucune transformation propre aux APC.

Cet ensemble parvient au SQL en descendant depuis la couche HTTP. La dépendance `get_apc_structure_ids`, dans `interfaces/api/deps.py`, se réduit à `perimeter_queries.get_persons_structure_ids_list(conn)` : elle ne contient aucune logique APC, le mot n'apparaissant que dans son nom et sa docstring. Six endpoints la reçoivent en paramètre — cinq dans `interfaces/api/routers/publications.py`, un dans `interfaces/api/routers/stats.py` — et repassent la liste aux query services.

Le paramètre `apc_structure_ids: list[int]` traverse ensuite toutes les couches. Il est déclaré dans six méthodes du port `application/ports/api/publications_queries.py` et quatre du port `application/ports/api/stats_queries.py`. Côté infrastructure, il se transmet à travers `queries/api/publications/__init__.py`, `facets.py` et `list.py`, `queries/api/stats/__init__.py`, `summary.py`, `pivot.py`, `collaborations.py`, `entity_facets.py` et `_shared.py`, jusqu'aux deux fonctions qui le consomment réellement : `apc_clause` dans `queries/filters.py` et `stats_apc_clause` dans `queries/api/stats/_shared.py`.

Le même besoin se satisfait ailleurs sans rien faire descendre. `PgLaboratoriesQueries.list_laboratories`, dans `infrastructure/queries/api/laboratories.py`, a besoin de la même liste et l'obtient par un appel à `get_persons_structure_ids_list(self._conn)` là où elle sert ; sa docstring l'énonce — « résout en interne le périmètre `persons` ». Deux appelants de la couche application font de même : `application/pipeline/affiliations/phase.py` et `application/services/authorships/core.py`.

Deux conséquences se constatent dans le code.

Le contrat de port oblige tout appelant, donc `interfaces/`, à connaître le périmètre APC pour avoir le droit de lister des publications ou de demander des statistiques. La règle « les structures internes pour les APC sont le périmètre des personnes » se trouve écrite dans le composition root, alors que c'est une décision applicative.

L'infrastructure ne peut pas dire ce que la liste contient, puisque son appelant la lui fournit : les docstrings de `apc_clause` et de `stats_apc_clause` s'en tirent par « typiquement le périmètre `perimeter_persons` ». Ce « typiquement » n'a pas de référent — aucun appelant ne passe autre chose.

Un bénéfice existe et se perdrait à traiter le sujet sans précaution : les constructeurs SQL sont testables sans périmètre en base, `tests/integration/infrastructure/queries/test_publications_list.py` et `test_stats_pivot.py` leur passant `apc_structure_ids=[]`.

## Décisions

Les adapters `PgPublicationsQueries` et `PgStatsQueries` résolvent le périmètre eux-mêmes, comme `PgLaboratoriesQueries` le fait déjà. Le paramètre disparaît des deux ports et des six endpoints ; la dépendance `get_apc_structure_ids` disparaît de `interfaces/api/deps.py`.

Le paramètre reste sur les fonctions privées d'infrastructure, celles qui construisent le SQL. C'est là qu'il porte le bénéfice de testabilité, et l'adapter est le seul à le leur fournir. La frontière du chantier est donc exactement la surface publique des adapters : au-dessus d'elle la liste n'existe plus, en dessous elle circule comme aujourd'hui.

La résolution se fait par appel dans chaque méthode publique d'adapter, sans cache d'instance. C'est le comportement de `PgLaboratoriesQueries`, et un endpoint appelle une méthode d'adapter par requête : le nombre de résolutions par requête reste de un, comme avec la dépendance actuelle.

Hors périmètre : la valeur `"uca"` codée en dur dans le vocabulaire du filtre `has_apc`, que lisent `apc_clause` et `stats_apc_clause`, ne change pas.

## Phasage

### Phase 1 — adapter publications

- [ ] `PgPublicationsQueries` résout le périmètre dans ses six méthodes publiques et le passe à ses constructeurs privés.
- [ ] Retrait de `apc_structure_ids` des six signatures du port `application/ports/api/publications_queries.py`.
- [ ] Les cinq endpoints de `interfaces/api/routers/publications.py` cessent de déclarer le paramètre.

### Phase 2 — adapter stats

- [ ] `PgStatsQueries` résout le périmètre dans ses quatre méthodes publiques et le passe à ses constructeurs privés.
- [ ] Retrait de `apc_structure_ids` des quatre signatures du port `application/ports/api/stats_queries.py`.
- [ ] L'endpoint de `interfaces/api/routers/stats.py` cesse de déclarer le paramètre.

### Phase 3 — retrait de la dépendance

- [ ] Suppression de `get_apc_structure_ids` de `interfaces/api/deps.py`.
- [ ] Les docstrings de `apc_clause` et `stats_apc_clause` nomment le périmètre au lieu de le supposer.

## Questions ouvertes

- Le nom `apc_structure_ids` qualifie d'APC un périmètre qui n'a rien de propre aux APC. Une fois la liste confinée sous les adapters, elle ne sert plus qu'aux deux clauses de filtre : le nom peut rester à leur frontière, ou devenir celui du périmètre qu'il désigne.
- Les deux adapters résoudront le périmètre par la fonction libre `get_persons_structure_ids_list`, comme `PgLaboratoriesQueries`, ou par le port `PerimeterQueries` qui l'expose déjà. La première est l'usage établi dans `infrastructure/queries/api/` ; la seconde laisse le périmètre injectable.
- `publications/facets.py` instancie plusieurs `_PublicationFacetsBuilder` par appel, dont un sur une connexion distincte. La résolution du périmètre se fait une fois dans la méthode publique et se passe aux constructeurs, ce qui suppose de vérifier qu'aucun chemin n'en ait besoin avant.
