# Pipeline

*À jour le 2026-10-30.*

Le pipeline est le traitement par lots qui moissonne les sources et en déduit le référentiel. Ses [phases](../pipeline/01-vue-d-ensemble.md) sont décrites avec le pipeline. C'est un paquet racine, hors des couches : chaque tâche contient son SQL. Il importe `domain/` et `infrastructure/`. Seul `interfaces/` l'importe, par `pipeline/public.py`.

## Organisation du paquet

| Module | Rôle |
|---|---|
| `run.py` | Orchestrateur, installé comme commande `run_pipeline` : choisit les phases du run et les exécute dans l'ordre |
| `graph.py` | Tâches du run, avec ce que chacune lit et écrit ; l'ordre des phases en découle |
| `task_runner.py` | Exécution des tâches d'une phase, dans l'ordre du graphe |
| `runtime/` | Contexte du run : modes, verrou d'exécution, transactions, parallélisme, observabilité |
| `ingestion/` | Un paquet par source : moissonnage, recherche par identifiant, normalisation. `common/` contient ce que les sources partagent, `complements/` les clients du DOAJ, de doi.org, du ROR, du Sudoc et d'Unpaywall |
| `transformation/` | Un paquet par domaine : structures, édition, publications, personnes, pays |
| `http/` | Clients HTTP : débit par source, nouvelles tentatives, circuit-breaker |
| `public.py` | Seul module que l'API importe : ordre des phases et recalculs ciblés |

## Phases et tâches

Le module de chaque phase expose `build()`, qui la construit avec ses dépendances. La phase s'exécute ensuite sur le contexte du run (`phase.run(ctx)`). Elle se compose de tâches. Le graphe déclare ce que chaque tâche lit et écrit, et les tests vérifient qu'aucune tâche ne lit une donnée écrite après elle.

Un verrou PostgreSQL limite chaque base à une exécution du pipeline à la fois. Les phases commitent par lots ([transactions](04-infrastructure.md#transactions)).

## Accès aux sources

Chaque source expose un adaptateur (`pipeline/ingestion/<source>/`) que les phases câblent : moissonneur, recherche par identifiant, normaliseur. Tout appel à une API tierce passe par `access_source`, qui saute l'étape quand les identifiants de la source manquent. Un circuit-breaker par source coupe les requêtes d'une source en panne : la phase passe en avertissement, et le run suivant reprend les éléments non traités.

## Recalculs déclenchés par l'API

Certaines éditions de l'administration déclenchent un recalcul ciblé, par exemple celui des publications d'une revue dont le type change. `application/ports/pipeline/` déclare chaque recalcul comme port. `pipeline/public.py` exporte les classes du pipeline qui les implémentent, et `interfaces/api/deps.py` les remet aux services.
