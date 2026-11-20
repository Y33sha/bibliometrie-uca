# Pipeline

*À jour le 2026-11-20.*

Le pipeline moissonne les sources, normalise leurs données, puis déduit les publications, les contributions et les personnes du référentiel. Le [guide d'exploitation](../exploitation/03-pipeline.md) décrit son lancement et ses options.

| Notion | Code | Définition |
|---|---|---|
| moissonnage | phases `harvest`, `harvest_by_person` et `fetch_*` du bloc `Block.HARVESTING` | Interrogation des sources vers `staging`, sur le périmètre puis par recherches ciblées |
| bloc | `Block` | Regroupement de phases à l'affichage |
| phase | `Phase` | Unité du run dans les journaux, l'administration, `--from` et `--only` |
| étape | `Step` | Regroupement de tâches d'une phase, décrit par une phrase d'entrées → sorties |
| tâche | `Task` | Feuille de l'arborescence, avec ses lectures et ses écritures |
| store | `*Store` | Accès SQL à une entité dans le pipeline |

Le module de chaque phase déclare ses étapes et ses tâches. L'arborescence donne l'ordre d'exécution. Les tests vérifient sa compatibilité avec les lectures et les écritures des tâches. `uv run python -m interfaces.cli.dev.pipeline_tree [PHASE] [--interface]` affiche l'arborescence.

## Phases

Les phases s'exécutent dans cet ordre, qui suit les dépendances entre tâches.

**Moissonnage et normalisation**

- `harvest` interroge les sources sur les affiliations du périmètre ([page](02-harvest.md)).
- `harvest_by_person` interroge les sources sur les identifiants des personnes du référentiel RH.
- `fetch_missing` cherche dans chaque source les documents trouvés dans une autre.
- `fetch_stale` cherche de nouveau les documents non revus depuis un délai, et repère ceux qui ont disparu de leur source.
- `fetch_truncated` complète les listes d'auteurs OpenAlex tronquées.
- [`normalize`](03-normalize.md) transforme les documents bruts en enregistrements sources et en contributions sources.

**Référentiels**

- [`structure_referentials`](04-affiliations.md#référentiels-ror-et-hal-structure_referentials) tient à jour les référentiels ROR et HAL.
- [`dois`](05-publishing.md#référentiel-des-doi-dois) tient le référentiel des DOI connus : agence de chaque préfixe, existence et URL de résolution chez doi.org.
- [`publishing`](05-publishing.md) complète les référentiels de l'édition.

**Enregistrements sources**

- [`identifier_arbitration`](09-persons.md#arbitrage-des-identifiants-identifier_arbitration) neutralise un identifiant de personne écrit sous le nom d'une autre personne.
- [`affiliations`](04-affiliations.md) reconnaît les structures des contributions sources, et marque leur entrée dans le périmètre.
- [`countries`](04-affiliations.md#pays-countries) reconnaît les pays des adresses, des contributions sources et des enregistrements sources.
- [`metadata_correction`](06-metadata-correction.md) corrige les enregistrements sources.

**Entités**

- [`publications`](07-publications.md) regroupe en publications les enregistrements sources qui décrivent le même document, puis recalcule les publications de la file de consolidation.
- [`author_grouping`](08-author-grouping.md) aligne en contributions les auteurs d'une publication, d'une source à l'autre.
- [`persons`](09-persons.md) rattache chaque contribution à une personne.

**Données dérivées**

- [`finalize`](10-finalize.md) purge les publications, reporte le périmètre sur les publications restantes, rafraîchit les vues des structures, nettoie les référentiels de l'édition et recompte.
- [`open_access`](11-enrichissements.md#statut-open-access-open_access) interroge Unpaywall sur le DOI des publications, puis recalcule leur statut open access.
- [`relations`](11-enrichissements.md) et `subjects` écrivent les relations entre publications et les sujets.
