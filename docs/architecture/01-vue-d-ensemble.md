# Architecture

*À jour le 2026-10-26.*

## Deux programmes, une base

Le code contient deux programmes qui communiquent seulement par la base PostgreSQL.

- **L'application web** (`interfaces/api/` et `interfaces/frontend/`) : un processus FastAPI permanent, qui répond aux requêtes des utilisateurs. Elle sert les pages, les listes, les tableaux de bord et les exports CSV.
- **Le pipeline** (paquet `pipeline/`, commande `run_pipeline`) : un traitement par lots, lancé par un ordonnanceur. Il moissonne les sources et en déduit le référentiel.

```
  sources externes
        │
        ▼  moissonnage
  ┌──────────────┐                ┌──────────────┐               ┌───────────────┐
  │   pipeline   │ ── écrit ────► │  base        │ ── lit ─────► │  application  │ ◄── utilisateurs
  │   (batch)    │                │  PostgreSQL  │               │  web (API     │
  │              │ ◄── relit ──── │              │ ◄── écrit ─── │  + frontend)  │
  └──────────────┘                └──────────────┘               └───────────────┘
```

Les données saisies dans l'administration (structures, périmètres, configuration, décisions humaines) sont des entrées relues et conservées par le pipeline à chaque exécution.

## Couches

Le code de l'application web suit une architecture hexagonale. Le pipeline, traitement par lots, se tient hors de ces couches.

- `domain/` contient les règles métier, sans entrée-sortie. Toutes les autres parties l'importent.
- `application/` contient les services d'écriture. Ils atteignent l'extérieur par des ports (`Protocol`) déclarés dans `application/ports/`.
- `infrastructure/` contient les adaptateurs sortants : SQL, journalisation. Ses repositories implémentent les ports de `application/ports/repositories/`.
- `interfaces/` contient les adaptateurs entrants : routes HTTP, frontend, scripts en ligne de commande. Son composition root instancie les implémentations des ports et les remet aux services.
- `pipeline/` contient les phases du traitement par lots. Il importe `domain/` et `infrastructure/`. Seul `interfaces/` l'importe, par `pipeline/public.py`. Ses recalculs implémentent les ports de `application/ports/pipeline/` ([page](06-pipeline.md)).

```
┌───────────────────────┐                     ┌────────────────────────┐
│ interfaces/           │                     │ pipeline/              │
│ routes, frontend, CLI │───── public.py ────►│ phases et tâches       │
│ composition roots     │                     └───┬────────────────┬───┘
└──┬────────────────┬───┘                         │                │
   │                ▼                             ▼                │
   │          ┌────────────────────────────────────────────┐       │
   │          │ infrastructure/                            │       │
   │          │ SQL, journalisation                        │       │
   │          └──────────────────────┬─────────────────────┘       │
   ▼                                 │                             │
┌───────────────────────┐            │                             │
│ application/          │            │                             │
│ services │ ports      │            │                             │
└───────────┬───────────┘            │                             │
            ▼                        ▼                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│ domain/   règles métier, sans entrée-sortie                          │
└──────────────────────────────────────────────────────────────────────┘
```

Les flèches sont les imports. Un port est un `Protocol` : ses implémentations le satisfont sans importer `application/`.

## Contrats d'import

Des contrats `import-linter`, déclarés dans `pyproject.toml`, vérifient ces règles. Un commentaire justifie chaque contrat.

**Couches**

- `Domain : rien hors bibliothèque standard` : `domain/` importe seulement la bibliothèque standard.
- `Couches DDD (layered)` : les imports vont de `interfaces/` vers `application/` et `infrastructure/`, puis vers `domain/`. `application/` atteint l'infrastructure par ses ports.
- `Adapters : la connexion se reçoit, elle ne s'ouvre pas` : les repositories et les lectures travaillent sur la connexion de leur appelant.

**Pipeline**

- `Pipeline : hors des couches hexagonales` : le pipeline importe `domain/` et `infrastructure/`, jamais `application/` ni `interfaces/`.
- `Pipeline : importé par interfaces seulement` : `domain/`, `application/` et `infrastructure/` ignorent le pipeline.
- `Pipeline : le noyau d'exécution ignore les phases` : le graphe des tâches et l'exécution ignorent les modules des phases.
- `Sources : les orchestrateurs de phase les importent, jamais l'inverse` : le module d'une source ignore les orchestrateurs de phase qui l'appellent.

**API**

- `Routers : pas d'import direct de infrastructure` : une route d'écriture reçoit un service, une route de lecture reçoit sa lecture de `infrastructure/read_models/`, par `Depends`.
- `Composition root : repositories concrets uniquement dans deps` : seul `interfaces/api/deps.py` instancie les repositories.
- `API : le pipeline par son interface publique` : l'API importe seulement `pipeline/public.py`.
- `API : aucune requête réseau sortante` : aucun module de l'API n'atteint un client réseau, même par une chaîne d'imports.
- `API : aucun lancement de programme` : aucun module de l'API n'atteint un lanceur de processus.

## Pages

- [`domain/`](02-domain.md)
- [`application/`](03-application.md)
- [`infrastructure/`](04-infrastructure.md), avec les transactions
- [`interfaces/`](05-interfaces.md)
- [`pipeline/`](06-pipeline.md)
- [Composition roots](07-composition-roots.md)
- [Tests](08-tests.md)
