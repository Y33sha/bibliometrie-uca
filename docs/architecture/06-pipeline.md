# Pipeline

*À jour le 2026-11-04.*

Le pipeline est le traitement par lots qui moissonne les sources et en déduit le référentiel. Ses [phases](../pipeline/01-vue-d-ensemble.md) sont décrites avec le pipeline. C'est un paquet racine, hors des couches : chaque tâche contient son SQL. Il importe `domain/` et `infrastructure/`. Seul `interfaces/` l'importe, par `pipeline/public.py`.

## Organisation du paquet

| Module | Rôle |
|---|---|
| `run.py` | Orchestrateur, installé comme commande `run_pipeline` : choisit les phases du run et les exécute dans l'ordre |
| `phases.py` | Phases du run dans l'ordre d'exécution, avec leurs tâches et leurs attributs |
| `graph.py` | Types `Task` et `Phase`, et dépendances entre tâches d'après leurs lectures et écritures |
| `task_runner.py` | Exécution d'une phase et de ses tâches |
| `runtime/` | Contexte du run : modes, verrou d'exécution, transactions, parallélisme, observabilité |
| `ingestion/` | Un paquet par source : moissonnage, recherche par identifiant, normalisation. `common/` contient le code partagé par les sources, `complements/` les clients du DOAJ, de doi.org, du ROR, du Sudoc et d'Unpaywall |
| `transformation/` | Un paquet par domaine : structures, édition, publications, personnes, pays |
| `http/` | Clients HTTP : débit par source, nouvelles tentatives, circuit-breaker |
| `public.py` | Seul module importé par l'API : ordre des phases et recalculs ciblés |

## Phases et tâches

Le module de chaque phase déclare ses tâches (`TASKS`) : lectures, écritures, API, fonction et affichage. `phases.py` groupe les tâches en phases. Une phase peut avoir une condition de mode, une précondition et un assemblage de ses métriques. `run_phase` exécute les tâches d'une phase dans leur ordre, sur le contexte du run. Les tests vérifient qu'aucune tâche ne lit une donnée écrite après elle.

Un verrou PostgreSQL limite chaque base à une exécution du pipeline à la fois. Les phases commitent par lots ([transactions](04-infrastructure.md#transactions)).

## Accès aux sources

Le paquet de chaque source (`pipeline/ingestion/<source>/`) déclare la lecture des documents reçus : identifiant, empreinte. Son module `adapter.py` déclare les implémentations utilisées par les tâches : moissonneurs, relecture par identifiant, recherche par DOI, normaliseur. Le code d'une source se charge à sa première demande. Tout appel à une API tierce passe par `access_source`, qui saute l'étape quand les identifiants de la source manquent. Un circuit-breaker par source coupe les requêtes d'une source en panne : la phase passe en avertissement, et le run suivant reprend les éléments non traités.

## Recalculs déclenchés par l'API

Certaines éditions de l'administration déclenchent un recalcul ciblé, par exemple celui des publications d'une revue retypée. `application/ports/pipeline/` déclare chaque recalcul comme port. `pipeline/public.py` exporte les classes du pipeline qui les implémentent, et `interfaces/api/deps.py` les remet aux services.
