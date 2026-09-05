# Application — services et orchestrateurs

*À jour le 2026-09-05.*

La couche applicative détermine le déroulé des opérations : dans quel ordre appeler les règles du domaine et les adaptateurs, et où placer la frontière transactionnelle. Elle n'écrit elle-même ni SQL ni appel réseau.

- **Services métier** (`application/services/`), un sous-package par agrégat. `commands.py` y porte les commandes de l'API — une commande, une transaction, un `commit` au succès ; `core.py` porte les opérations que l'API et le pipeline partagent. Le journal d'audit vit à part, dans `application/audit_log.py`.
- **Orchestrateurs pipeline** dans `application/pipeline/` : un sous-package par phase. Chaque orchestrateur séquence sa phase et délègue HTTP et SQL à des adaptateurs. L'inventaire phase par phase, avec entrées et sorties, vit dans la [documentation du pipeline](../pipeline/01-vue-d-ensemble.md).
- **Ports** (`application/ports/`) : les interfaces `Protocol` par lesquelles services et orchestrateurs atteignent l'extérieur.

## Patterns d'injection

Deux styles cohabitent, selon que la connexion est ouverte ou non au moment du câblage.

- **Services de l'API** : la requête a ouvert sa transaction avant l'appel. Le router construit les repositories sur cette connexion et les passe au service.
- **Phases du pipeline** : la phase ouvre ses transactions elle-même, et `metadata_correction` en ouvre trois de suite. Rien ne peut donc être construit au moment du câblage : la phase reçoit une fabrique `Callable[[Connection], PersonRepository]`, qu'elle appelle une fois la connexion ouverte.

## Transactions

La règle générale est que les transactions sont ouvertes et commitées par le use-case, non par l'adaptateur (cf. [discipline transactionnelle](04-infrastructure.md#discipline-transactionnelle)).

Côté pipeline, les phases qui traitent de grands ensembles commitent **par batch** (toutes les N opérations) pour qu'un plantage ne perde pas le travail déjà fait. Les phases étant idempotentes, une reprise ne casse rien.

## Ports

Un port est un `Protocol` déclaré par `application/` et implémenté par un adaptateur d'`infrastructure/`. Trois familles :

- **Repositories** (`ports/repositories/`) — chargent et persistent un agrégat du domaine quand il y en a un. Quatre n'en ont pas : `Address`, `Authorship`, `AuditLog` et `Config` font du CRUD simple.
- **Read models** (`ports/read_models/`) — projections plates que l'API sert aux pages.
- **Gateways de pipeline** (`ports/pipeline/`) — lectures et écritures ensemblistes des tables d'une phase.

Une même donnée se lit et s'écrit depuis deux contextes : le pipeline la recalcule en masse, l'API la sert ou la retouche après une édition manuelle. Chacun a ses ports et ses adaptateurs.
