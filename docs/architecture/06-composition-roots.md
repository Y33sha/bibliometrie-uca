# Composition roots

*À jour le 2026-09-05.*

Un composition root est l'endroit où les adaptateurs concrets sont instanciés et câblés aux use-cases. Ailleurs, on reçoit un port en paramètre.

## Où ils sont

**L'API en a deux.** `app.py` construit l'engine au démarrage et le libère à l'arrêt ; `deps.py` porte les fabriques qui câblent repositories, read models et gateways sur la connexion de la requête, et que les routes reçoivent par `Depends`. Les routers, eux, n'importent pas `infrastructure/`.

**Chaque programme en ligne de commande est son propre composition root.** Dans `run_pipeline`, des wrappers `_run_*` ouvrent la connexion, instancient les adaptateurs et appellent l'orchestrateur applicatif de la phase. Les scripts d'import, de maintenance et les backfills font de même, sans la séparation entre construction et appel que l'API impose.

## Règles d'import

Les contrats `import-linter` ferment tous les autres chemins. `domain/` et `application/` n'atteignent pas `infrastructure/`, le contrat de couches l'interdisant. Sous `interfaces.api`, les routers ne l'importent pas du tout, et les trois familles d'adaptateurs ne s'ouvrent qu'à `deps.py`.

Peuvent donc atteindre `infrastructure/` : `app.py` et `deps.py`, les programmes de `interfaces/cli/`, et `infrastructure/` lui-même.
