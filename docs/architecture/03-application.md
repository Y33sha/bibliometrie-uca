# Application — services

*À jour le 2026-09-05.*

La couche applicative détermine le déroulé des opérations : dans quel ordre appeler les règles du domaine et les adaptateurs, et où placer la frontière transactionnelle. Elle n'écrit elle-même ni SQL ni appel réseau.

- **Services** (`application/services/`), un sous-package par agrégat. `commands.py` y contient les commandes de l'API — une commande, une transaction, un `commit` au succès (cf. [transactions](04-infrastructure.md#transactions)) ; `core.py` contient les opérations de l'agrégat. Le journal d'audit vit à part, dans `application/audit_log.py`.
- **Ports** (`application/ports/`) : les interfaces `Protocol` par lesquelles les services atteignent l'extérieur.

## Injection

La requête a ouvert sa transaction avant l'appel. Le router construit les repositories sur cette connexion et les passe au service.

## Ports

Un port est un `Protocol` déclaré par `application/` et implémenté par un adaptateur d'`infrastructure/` ou par le pipeline. Trois familles :

- **Repositories** (`ports/repositories/`) — chargent et persistent un agrégat du domaine quand il y en a un. Quatre n'en ont pas : `Address`, `Authorship`, `AuditLog` et `Config` font du CRUD simple.
- **Read models** (`ports/read_models/`) — projections plates que l'API sert aux pages.
- **Recalculs du pipeline** (`ports/pipeline/`) — recalculs ciblés que les services déclenchent après une édition. `interfaces/api/deps.py` les remplit depuis `pipeline/public.py`.

Une même donnée se lit et s'écrit depuis deux contextes : le pipeline la recalcule en masse, l'API la sert ou la retouche après une édition manuelle.
