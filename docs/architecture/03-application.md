# Application — services

*À jour le 2026-10-25.*

La couche applicative détermine le déroulé des opérations : dans quel ordre appeler les règles du domaine et les adaptateurs. Elle n'écrit elle-même ni SQL ni appel réseau.

- **Services** (`application/services/`), un sous-package par agrégat. Ils appliquent la règle métier ; leur appelant commite la transaction (cf. [transactions](04-infrastructure.md#transactions)).
- **Journal d'audit** (`application/audit_log.py`) : les services y déposent leurs événements, que la requête d'administration écrit avec son commit.
- **Ports** (`application/ports/`) : les interfaces `Protocol` par lesquelles les services atteignent l'extérieur.

## Injection

La requête a ouvert sa transaction avant l'appel. Le router construit les repositories sur cette connexion et les passe au service.

## Ports

Un port est un `Protocol` déclaré par `application/` et implémenté par un adaptateur d'`infrastructure/` ou par le pipeline. Trois familles :

- **Repositories** (`ports/repositories/`) — chargent et persistent un agrégat du domaine quand il y en a un. Quatre n'en ont pas : `Address`, `Contribution`, `AuditLog` et `Config` font du CRUD simple.
- **Read models** (`ports/read_models/`) — projections plates que l'API sert aux pages.
- **Recalculs du pipeline** (`ports/pipeline/`) — recalculs ciblés que les services déclenchent après une édition. `interfaces/api/deps.py` les remplit depuis `pipeline/public.py`.

Une même donnée se lit et s'écrit depuis deux contextes : le pipeline la recalcule en masse, l'API la sert ou la retouche après une édition manuelle.
