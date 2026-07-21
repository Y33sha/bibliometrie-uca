# Application — services et orchestrateurs

*À jour le 2026-06-30.*

Contenu :

- **Services métier**, un sous-package par agrégat exposant un module `core.py` : `persons/core.py`, `publications/core.py`, `journals/core.py`, `structures/core.py`, `publishers/core.py`, `config/core.py`, auxquels s'ajoutent `authorships/core.py` et `authorships/assign_orphans.py`, `addresses/countries.py`, et `audit.py` (module plat). Ces services reçoivent leurs dépendances par injection (kwarg `repo=`, `audit_repo=`, `queries=`).
- **Orchestrateurs pipeline** dans `application/pipeline/` : un sous-package par phase. Chaque orchestrateur séquence sa phase et délègue HTTP et SQL à des adapters via des ports (`application/ports/pipeline/*`), sans jamais importer `infrastructure/` directement. L'inventaire phase par phase, avec entrées et sorties, vit dans la [documentation du pipeline](../pipeline/01-vue-d-ensemble.md).
- **Ports** (`application/ports/*`) : interfaces Protocol pour les query services (adapters dans `infrastructure/queries/*`) et pour les repositories (`application/ports/repositories/*`, implémentés dans `infrastructure/repositories/*`). Un repository charge et persiste un agrégat du domaine quand il y en a un ; sinon il fait du CRUD de table ou de l'append (`Config`, `AuditLog`, `DoiPrefix`, `Address`).

## Patterns d'injection

Toute dépendance vers un adapter sortant passe par un port, instancié uniquement aux composition roots (cf. [06-composition-roots.md](06-composition-roots.md)). Deux styles cohabitent :

- **Services applicatifs** : ils reçoivent leurs dépendances (repository, query service, audit) en arguments keyword-only ; le caller (router, test, script CLI) les instancie via les factories de `infrastructure/repositories`.
- **Orchestrateurs pipeline** : les query services sont passés en paramètre, typés par un port `application/ports/*`. Pour un repository, dont la `Connection` n'est pas connue à la construction, on injecte un *factory callable* `Callable[[Connection], XRepository]` que l'orchestrateur appelle une fois la connexion ouverte.

### Batch commits dans le pipeline

La règle générale est que les use-cases commitent (cf. [discipline transactionnelle](04-infrastructure.md#discipline-transactionnelle)). Côté pipeline, les phases qui traitent des dizaines de milliers d'items commitent **par batch** (toutes les N opérations) pour qu'un crash ne perde pas tout le travail déjà fait ; cela suppose des phases idempotentes (vrai par construction). Les phases concernées sont listées dans la discipline transactionnelle de l'infrastructure (cf. [04-infrastructure.md](04-infrastructure.md#discipline-transactionnelle)).

## Ports par contexte

Une même donnée se lit et s'écrit depuis deux contextes : le pipeline la recalcule en masse, l'API la sert ou la retouche après une édition de curation. Chacun a son port et son adaptateur, rangés selon leur contexte — `application/ports/pipeline/*` et `infrastructure/queries/pipeline/*` d'un côté, `application/ports/api/*` et `infrastructure/queries/api/*` de l'autre. Les sujets en donnent l'exemple : le port d'ingestion `application/ports/pipeline/subjects.py` écrit le référentiel, le port de lecture `application/ports/api/subjects_queries.py` le sert au router, et leurs deux adaptateurs vivent chacun dans leur dossier.

La contrainte porte sur la couche application : une brique applicative ne dépend que du port de son propre contexte — `application/ports/pipeline/*` pour un orchestrateur de phase, `application/ports/api/*` (ou le port de repository de la ressource visée) pour un service d'écriture API. Un service API n'importe jamais un port pipeline, ni l'inverse ; des contrats import-linter le vérifient. Du SQL commun aux deux contextes se partage dans l'infrastructure, sans que les couches applicatives ne se couplent entre elles.
