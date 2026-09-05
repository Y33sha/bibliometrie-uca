# Vue d'ensemble

*À jour le 2026-09-05.*

Le système se lit selon deux axes complémentaires : **deux programmes** couplés par la base de données (vue d'exécution), et **quatre couches** organisant le code à l'intérieur de chaque programme (vue logicielle).

## Deux programmes, une base

Le code héberge deux programmes de natures différentes, qui ne s'appellent jamais directement : ils ne communiquent qu'à travers la base PostgreSQL.

- **L'application web** (`interfaces/api/` + `interfaces/frontend/`) : un processus FastAPI permanent, piloté par les requêtes des utilisateurs. Elle sert les pages web et restitue les données sous forme de listes, tableaux de bord et exports CSV.
- **Le pipeline** (`run_pipeline` + `application/pipeline/`) : un traitement par lots, déclenché par un ordonnanceur. Il **dérive** le référentiel : moissonnage des sources, normalisation, déduplication, rapprochement, enrichissements.

```
  sources externes
        │
        ▼  moissonnage
  ┌──────────────┐                ┌──────────────┐               ┌───────────────┐
  │   pipeline   │ ── écrit ────► │  base        │ ── lit ─────► │  application  │ ◄── utilisateurs
  │   (batch)    │   (dérive)     │  PostgreSQL  │               │  web (API     │
  │              │ ◄── relit ──── │              │ ◄── écrit ─── │  + frontend)  │
  └──────────────┘   la curation  └──────────────┘   curation    └───────────────┘
```

La curation forme une **boucle fermée** : les corrections saisies via l'API — données de référence (structures, périmètre, configuration) et arbitrages manuels (*cannot-link* entre personnes ou entre publications, identifiants confirmés ou rejetés…) — deviennent des **entrées** que le pipeline relit et **préserve** à chaque passe.

## Vue par couches

Le projet suit une architecture **hexagonale (DDD)**. Le cœur du système est `application/` (use-cases et orchestrateurs), qui dépend de `domain/` (noyau pur). Autour de ce cœur, deux familles d'adapters : `interfaces/` (entrants — HTTP, CLI) et `infrastructure/` (sortants — base, APIs externes, logs). Aucune des deux n'importe l'autre ; leur neutralité repose sur les **ports** (`Protocol`) définis dans `application/ports/`, dont dépendent tous les autres modules.

Cette vue par couches se superpose à la vue par programme : `domain/` sert aux deux programmes, tandis que les couches extérieures se répartissent entre l'application web et le pipeline, quelques modules restant partagés. Le détail se lit dans les fiches de chaque couche.


```
                  ┌─────────────────────────────┐
                  │  domain/                    │
                  │  entités, value objects,    │
                  │  règles métier pures        │  (zéro I/O)
                  └──────────────▲──────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │  application/               │
                  │  ├─ ports/    (Protocol)    │  ← zone neutre
                  │  └─ use-cases, orchestrateurs
                  └─────▲────────────────▲──────┘
                        │                │
            ┌───────────┘                └──────────────┐
            │                                           │
    ┌───────┴─────────┐                       ┌─────────┴─────────┐
    │  interfaces/    │    ─── ⊥ ───          │  infrastructure/  │
    │  adapters       │   (pas d'import       │  adapters sortants│
    │  entrants :     │   direct l'un de      │  (SQL, APIs       │
    │  routers, CLI   │   l'autre)            │  externes, logs)  │
    └─────────────────┘                       └───────────────────┘
```

## Contrats d'architecture

Chaque règle est vérifiée par un contrat `import-linter`, déclaré dans `pyproject.toml`, section `[tool.importlinter]`, et nommé ici en regard.

1. **Le noyau n'importe que la bibliothèque standard.** `domain/` n'atteint aucun paquet tiers et aucune autre couche. Les modules permis sont ceux que Python publie pour sa version, dans `sys.stdlib_module_names`.
   → `Domain : rien hors bibliothèque standard`

2. **Les couches ne s'importent que vers le bas.** `interfaces/` au-dessus, `infrastructure/` et `application/` au milieu, `domain/` en dessous. En particulier, `application/` n'importe pas `infrastructure/` : les services applicatifs reçoivent leurs dépendances par les **ports** (`Protocol`) de `application/ports/`, que `infrastructure/` implémente.
   → `Couches DDD (layered)`

3. **Les routers n'atteignent pas `infrastructure/` directement.** Ils reçoivent leurs dépendances par `Depends(...)`, dont les fabriques vivent dans `interfaces/api/deps.py`. Le chemin indirect qui passe par ces fabriques reste permis.
   → `Routers : pas d'import direct de infrastructure`

4. **Seul le composition root instancie les adapters concrets.** Pour l'application web, ce sont `interfaces/api/app.py` et `interfaces/api/deps.py` ; partout ailleurs sous `interfaces/api/`, on passe par un port. Chaque script de `interfaces/cli/` est son propre composition root.
   → `Composition root : Pg* concrets uniquement dans app et deps`

5. **Un adapter reçoit sa connexion, il ne l'ouvre pas.** Les modules de lecture et les repositories travaillent sur la connexion que leur appelant leur remet.
   → `Adapters : la connexion se reçoit, elle ne s'ouvre pas`

6. **L'API n'émet aucune requête réseau.** Aucun module servant une requête HTTP n'atteint un client réseau, y compris par une chaîne d'imports. Tout le trafic sortant appartient au pipeline.
   → `API : aucune requête réseau sortante`

7. **L'API ne lance aucun programme.** Aucun module de la couche API n'atteint un lanceur de processus, directement ou indirectement.
   → `API : aucun lancement de programme`

## Suite

- [`domain/`](02-domain.md) — entités et logique métier
- [`application/`](03-application.md) — services, orchestrateurs, injection des dépendances
- [`infrastructure/`](04-infrastructure.md) — adapters sortants, discipline transactionnelle
- [`interfaces/`](05-interfaces.md) — adapters entrants
- [Composition roots](06-composition-roots.md) — instanciation et câblage des adapters
- [Tests](07-tests.md) — tests unitaires, tests d'intégration, couverture
