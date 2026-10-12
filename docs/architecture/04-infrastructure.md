# Infrastructure — adaptateurs sortants

*À jour le 2026-09-05.*

`infrastructure/` implémente les [ports](03-application.md#ports) : SQL, journalisation. Seuls les composition roots et le pipeline l'importent.

## Contenu

- **`db/`** — engine, modèle des tables, types SQL
- **`repositories/`**, **`read_models/`** — les deux familles d'adaptateurs SQL
- **`jsonb_models/`** — modèles Pydantic des colonnes JSONB, qui valident à l'écriture et typent la lecture
- **`raw_store/`** — écrit et relit le store de payloads bruts, hors base (`data/raw_store` par défaut)
- **`observability/`** — journalisation JSON et historique d'exécution des phases
- **`settings.py`** — configuration lue depuis l'environnement

## Familles d'adaptateurs

Les adaptateurs de `repositories/` construisent des objets du domaine : ils hydratent un agrégat, garantissent ses invariants à l'écriture, et exposent des signatures métier (`find_by_doi`, `merge_into`, `save`). Le passage d'une ligne SQL à l'entité se fait dans une fonction libre `_<entité>_from_row`, au sein du module du repository.

`read_models/` rend des lignes, sans hydratation : des projections plates que les routers passent à leur modèle Pydantic.

## Transactions

La règle générale est qu'une unité de travail tient dans une transaction, ouverte et commitée par le service ou l'orchestrateur, non par l'adaptateur.

Les phases du pipeline qui traitent de grands ensembles commitent par lots, toutes les N opérations, si bien qu'un plantage ne perd que le dernier lot. À l'intérieur d'un lot, chaque item est isolé dans un savepoint : une erreur annule l'item fautif seul, sans emporter les autres.
