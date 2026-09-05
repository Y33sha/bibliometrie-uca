# Infrastructure — adaptateurs sortants

*À jour le 2026-09-05.*

`infrastructure/` implémente les [ports](03-application.md#ports) : SQL, appels aux APIs sources, journalisation. Seuls les composition roots l'importent.

## Contenu

- **`db/`** — engine, modèle des tables, types SQL et garde-fous
- **`repositories/`**, **`read_models/`**, **`pipeline/`** — les trois familles d'adaptateurs SQL
- **`sources/`** — clients des APIs distantes
- **`jsonb_models/`** — modèles Pydantic des colonnes JSONB, qui valident à l'écriture et typent la lecture
- **`raw_store/`** — écrit et relit le store de payloads bruts, hors base (`data/raw_store` par défaut) : les réponses des sources y sont gardées pour re-normalisation et audit
- **`observability/`** — journalisation JSON et historique d'exécution des phases
- **`pipeline_lock.py`** — verrou interdisant deux `run_pipeline` simultanés, qui produiraient des deadlocks Postgres et des états incohérents
- **`settings.py`**, **`parallel.py`** — configuration lue depuis l'environnement, exécution parallèle par threads

## Familles d'adaptateurs

Les adaptateurs de `repositories/` construisent des objets du domaine : ils hydratent un agrégat, garantissent ses invariants à l'écriture, et exposent des signatures métier (`find_by_doi`, `merge_into`, `save`). Le passage d'une ligne SQL à l'entité se fait dans une fonction libre `_<entité>_from_row`, au sein du module du repository.

Les deux autres rendent des lignes, sans hydratation. `read_models/` produit des projections plates que les routers passent à leur modèle Pydantic ; `pipeline/` lit et écrit par ensembles — marquage d'état, vidange de `staging`, matérialisation des sorties d'une phase.

`sources/` forme une famille à part : ses adaptateurs sont les seuls à appeler l'extérieur. Ils interrogent les APIs distantes, gèrent la limitation de débit et déposent les réponses dans `staging`.

## Transactions

La règle générale est qu'une unité de travail tient dans une transaction, ouverte et commitée par le use-case, non par l'adaptateur.

Les phases du pipeline qui traitent de grands ensembles commitent par lots, toutes les N opérations, si bien qu'un plantage ne perd que le dernier lot. À l'intérieur d'un lot, chaque item est isolé dans un savepoint : une erreur annule l'item fautif seul, sans emporter les autres.
