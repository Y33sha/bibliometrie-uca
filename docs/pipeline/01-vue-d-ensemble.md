# Pipeline

*À jour le 2026-10-26.*

Le pipeline moissonne les sources, normalise leurs données, puis déduit les publications, les contributions et les personnes du référentiel. Le [guide d'exploitation](../exploitation/03-pipeline.md) décrit son lancement et ses options.

| Notion | Code | Définition |
|---|---|---|
| moissonnage | phases `harvest` et `harvest_by_person`, protocole `Harvester` | Collecte des sources |
| phase | `Phase` | Unité du run dans les journaux et l'administration |
| tâche | `Task` | Étape du graphe du run (`pipeline/graph.py`), avec ses lectures et ses écritures |
| store | `*Store` | Accès SQL à une entité dans le pipeline |

## Phases

Les phases s'exécutent dans cet ordre.

**Moissonnage** ([page](02-harvest.md))

- `harvest` interroge les sources sur les affiliations du périmètre.
- `harvest_by_person` interroge les sources sur les identifiants des personnes du référentiel RH.
- `fetch_missing` cherche dans chaque source les documents trouvés dans les autres.
- `fetch_stale` rafraîchit les documents non revus depuis un délai, et repère ceux qui ont disparu de leur source.
- `fetch_truncated` retélécharge les documents OpenAlex à liste d'auteurs tronquée.

**Enregistrements sources**

- [`normalize`](03-normalize.md) transforme les données moissonnées en enregistrements sources et en contributions sources.
- [`affiliations`](04-affiliations.md) reconnaît les structures dans les adresses, et marque l'entrée des contributions sources dans le périmètre.
- [`resolve_ra` et `publishing`](05-publishing.md) complètent les référentiels de l'édition.
- [`metadata_correction`](06-metadata-correction.md) corrige les métadonnées des enregistrements sources.

**Référentiel**

- [`publications`](07-publications.md) regroupe les enregistrements sources qui décrivent le même document en publications.
- [`author_grouping`](08-author-grouping.md) aligne les contributions sources d'un même auteur dans une contribution.
- [`persons`](09-persons.md) rattache chaque contribution à une personne.
- [`finalize`](10-finalize.md) reporte le périmètre sur les publications, rafraîchit les vues des structures, purge et recompte.

**Enrichissements** ([page](11-enrichissements.md)). `relations`, `subjects`, `countries` et `oa_status` écrivent les relations entre publications, les sujets, les pays et le statut open access. L'option `--no-extras` les omet.
