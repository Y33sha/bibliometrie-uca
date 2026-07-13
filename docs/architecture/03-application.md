# Application — services et orchestrateurs

*À jour le 2026-06-30.*

Contenu :

- **Services métier**, un sous-package par agrégat exposant un module `core.py` : `persons/core.py`, `publications/core.py`, `journals/core.py`, `structures/core.py`, `publishers/core.py`, `config/core.py`, auxquels s'ajoutent `authorships/core.py` et `authorships/assign_orphans.py`, `addresses/countries.py`, et `audit.py` (module plat). Ces services reçoivent leurs dépendances par injection (kwarg `repo=`, `audit_repo=`, `queries=`).
- **Orchestrateurs pipeline** dans `application/pipeline/` : un sous-package par phase. Chaque orchestrateur séquence sa phase et délègue HTTP et SQL à des adapters via des ports (`application/ports/pipeline/*`), sans jamais importer `infrastructure/` directement. L'inventaire phase par phase, avec entrées et sorties, vit dans la [documentation du pipeline](../pipeline/01-vue-d-ensemble.md).
- **Ports** (`application/ports/*`) : interfaces Protocol pour les query services (adapters dans `infrastructure/queries/*`) et pour les repositories d'agrégats (`application/ports/repositories/*`, implémentés dans `infrastructure/repositories/*`).

## Patterns d'injection

Toute dépendance vers un adapter sortant passe par un port, instancié uniquement aux composition roots (cf. [06-composition-roots.md](06-composition-roots.md)). Deux styles cohabitent :

- **Services applicatifs** : ils reçoivent leurs dépendances (repository, query service, audit) en arguments keyword-only ; le caller (router, test, script CLI) les instancie via les factories de `infrastructure/repositories`.
- **Orchestrateurs pipeline** : les query services sont passés en paramètre, typés par un port `application/ports/*`. Pour un repository, dont la `Connection` n'est pas connue à la construction, on injecte un *factory callable* `Callable[[Connection], XRepository]` que l'orchestrateur appelle une fois la connexion ouverte.

### Batch commits dans le pipeline

La règle générale est que les use-cases commitent (cf. [discipline transactionnelle](04-infrastructure.md#discipline-transactionnelle)). Côté pipeline, les phases qui traitent des dizaines de milliers d'items commitent **par batch** (toutes les N opérations) pour qu'un crash ne perde pas tout le travail déjà fait ; cela suppose des phases idempotentes (vrai par construction). Les phases concernées sont listées dans la discipline transactionnelle de l'infrastructure (cf. [04-infrastructure.md](04-infrastructure.md#discipline-transactionnelle)).

## Queries mutualisées et ports par contexte

Le recalcul d'un cache dénormalisé (par exemple `journals.pub_count`, `addresses.countries`, les cooccurrences de sujets) sert deux contextes : le pipeline le recalcule en masse, l'API le recalcule de façon ciblée après une édition de curation. Le SQL correspondant est mutualisé dans un module `infrastructure/queries/*`, qui peut héberger plusieurs adaptateurs. Ainsi `infrastructure/queries/subjects.py` expose `PgSubjectsQueries`, adaptateur du port pipeline `application/ports/pipeline/subjects.py`, et `PgSubjectsAdminQueries`, adaptateur du port API `application/ports/api/subjects_queries.py`.

Le partage reste confiné à l'infrastructure. La contrainte porte sur la couche application : une brique applicative ne dépend que du port de son propre contexte — `application/ports/pipeline/*` pour un orchestrateur de phase, `application/ports/api/*` (ou le port de repository de l'agrégat visé) pour un service d'écriture API. Un service API n'importe jamais un port pipeline, ni l'inverse. Deux adaptateurs de contextes différents peuvent donc partager des fragments de requête sans que les couches applicatives ne se couplent entre elles.

Cette frontière garde chaque contexte remplaçable indépendamment : réécrire la surface API dans une autre technologie ne réimplémente que les adaptateurs du contexte API, tandis que le module d'infrastructure mutualisé continue de servir le pipeline.
