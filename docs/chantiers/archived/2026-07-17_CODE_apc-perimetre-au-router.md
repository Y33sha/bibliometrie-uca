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

### Ce que « interne » veut dire

Le relevé des données éclaire ce que le filtre classe, et confirme que le classement est celui voulu.

`apc_payments.budget_structure_id` porte le **financeur** : six valeurs distinctes seulement — CNRS (9 835 paiements), Inserm (5 165), INRAE (2 663), IRD (1 010), UCA (341), AgroParisTech (34). Le labo, lui, vit dans `lab_structure_id` (25 valeurs, 302 lignes). Le périmètre `uca` réunissant l'établissement et ses 45 laboratoires, seule la structure « UCA » peut donc matcher `budget_structure_id` : `has_apc=uca` retient 341 paiements sur 37 566.

C'est le résultat attendu. « Interne » signifie **payé sur le budget de l'établissement**, non « payé pour l'un de nos laboratoires » : un APC réglé par le CNRS pour une UMR co-tutelle relève du budget du CNRS. Les 18 707 paiements ainsi classés `non_uca` le sont à juste titre.

Aucun code du dépôt n'écrit `budget_structure_id` — `import_openapc.py` ne renseigne que `institution`, en texte libre. Les rattachements viennent des chargements `enquete_apc` et `fp_hors_oa`, hors dépôt.

## Phasage

### Phase 1 — adapter publications

- [x] `PgPublicationsQueries` résout le périmètre dans les cinq méthodes publiques qui le consomment et le passe à ses constructeurs privés.
- [x] Retrait du paramètre des cinq signatures du port `application/ports/api/publications_queries.py`.
- [x] Les cinq endpoints de `interfaces/api/routers/publications.py` cessent de déclarer le paramètre.

### Phase 2 — adapter stats

- [x] `PgStatsQueries` résout le périmètre dans ses quatre méthodes publiques et le passe à ses constructeurs privés.
- [x] Retrait du paramètre des quatre signatures du port `application/ports/api/stats_queries.py`.
- [x] `StatsFilters` et sa dépendance, dans `interfaces/api/routers/stats.py`, cessent de le porter.

### Phase 3 — retrait de la dépendance

- [x] Suppression de `get_apc_structure_ids` de `interfaces/api/deps.py`.
- [x] Les docstrings de `apc_clause` et `stats_apc_clause` nomment le périmètre au lieu de le supposer.
- [x] Sous les adapters, le paramètre devient `perimeter_structure_ids`.

## Questions ouvertes

Aucune. Les trois points ouverts au cadrage se sont tranchés à l'exécution :

- **Le nom.** Sous les adapters, le paramètre s'appelle `perimeter_structure_ids`, du périmètre qu'il désigne. Le préfixe `apc` ne subsiste que sur les binds SQL des deux clauses, locaux à leur requête.
- **La résolution** passe par la fonction libre `get_persons_structure_ids_list`, usage établi dans `infrastructure/queries/api/` et celui de `PgLaboratoriesQueries`. Le port `PerimeterQueries` supposerait de l'injecter dans deux adapters qui portent déjà leur connexion, sans bénéfice.
- **`publications/facets.py`** : la méthode publique résout le périmètre une fois et passe la liste à tous les `_PublicationFacetsBuilder`, celui sur connexion distincte compris. Aucun chemin n'en a besoin plus tôt.
