# Enrichissement des référentiels publishers et journals

*À jour le 2026-06-30.*

Phase `publishers_journals` : enrichit le référentiel `journals` (revues) à partir de sources externes, après sa création initiale en phase [normalize](03-normalize.md).

Trois sous-étapes. `resolve_publishers` s'exécute à chaque lancement du pipeline ; les deux enrichissements journaux ne tournent que lorsque l'enrichissement des référentiels est activé pour le mode courant (drapeau de politique `run_journal_enrichment`, vrai en mode `full`).

| Sous-étape | Source externe | Ce qu'elle renseigne | Quand |
|---|---|---|---|
| `resolve_publishers` | Crossref `/prefixes/{prefix}` + DataCite `/dois?prefix=` | `doi_prefixes` : pour chaque préfixe DOI déjà routé vers sa Registration Agency par la phase [resolve_ra](02-extract.md#resolve-ra), l'éditeur (Crossref) ou l'entrepôt (DataCite) qui le détient, et le `publisher_id` rattaché | toujours |
| `enrich_journals_from_openalex` | [OpenAlex Sources](../sources/03-openalex.md) | `journals` : type de revue, montant et devise des frais de publication (APC) | mode `full` |
| `enrich_journals_from_doaj` | export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj) | `journals` : fiche DOAJ complète (`doaj_payload`) et appartenance au DOAJ (`is_in_doaj`) | mode `full` |

Le `journal_type` posé ici nourrit la correction `journal_type → doc_type` de la phase [metadata_correction](06-metadata-correction.md), d'où sa place dans le pipeline.

## Enrichissement des éditeurs : hors pipeline

Les champs d'éditeur enrichis depuis des sources externes — `country` (pays), `ror`, `publisher_type` — sont **purement cosmétiques** (affichage) : aucune phase du pipeline ne les consomme. Ils sont donc enrichis **à la demande**, par le script de maintenance `interfaces/cli/maintenance/enrich_publishers.py`, qui enchaîne trois sources sur une même connexion :

| Étape | Source externe | Ce qu'elle renseigne |
|---|---|---|
| OpenAlex Publishers | [OpenAlex](../sources/03-openalex.md) | `country` (ISO-2) + `ror` |
| Crossref Members | [Crossref](../sources/06-crossref.md) | `country` (rattrapage des éditeurs sans pays après OpenAlex, reliés à un membre Crossref via `doi_prefixes`) |
| ROR | [ROR](../sources/09-sources-supplementaires.md#ror) | `publisher_type` (`commercial`, `academic_institution`, `learned_society`, `repository`), dérivé du `ror` posé par OpenAlex |

Lancement : `python -m interfaces.cli.maintenance.enrich_publishers [--limit N] [--dry-run]`. Politique « NULL/unknown only » : ne touche jamais une valeur saisie par un administrateur.

## DOAJ : import par export complet

Le DOAJ publie chaque semaine un export complet de son catalogue, sous forme d'un fichier CSV. La sous-étape télécharge cet export, puis met à jour toutes les revues en une passe, par appariement sur l'ISSN : elle écrit la fiche DOAJ (`doaj_payload`) et le drapeau `is_in_doaj`.

Pour `is_in_doaj`, le DOAJ fait autorité : le drapeau est remis à `false` partout, puis remis à `true` pour les seules revues présentes dans l'export. L'export n'est re-téléchargé qu'au plus une fois tous les 30 jours (il est conservé dans `data/doaj/`) ; tant que le dernier import est plus récent que ce seuil, la sous-étape est entièrement sautée.

## Idempotence

Chaque sous-étape est incrémentale — filtres d'éligibilité :

- `resolve_publishers` : préfixes dont la Registration Agency est résolue mais dont l'éditeur n'a pas encore été interrogé (`publisher_id` et `publisher_checked_at` nuls). Chaque préfixe est marqué « interrogé » quoi qu'il advienne, pour ne pas être retenté indéfiniment quand l'API ne renseigne aucun éditeur.
- `enrich_journals_from_openalex` : revues ayant un `openalex_id` et un type encore inconnu (`journal_type = 'unknown'`). Converge à zéro : OpenAlex type ses sources, une revue typée sort de la file.
- `enrich_journals_from_doaj` : déclenché par l'âge du dernier import (voir ci-dessus), et non par un filtre revue par revue.

Le script de maintenance des éditeurs est lui aussi incrémental (éditeurs au champ encore manquant). Politique d'écrasement, partout : une valeur n'est posée que si la cible est vide. Les valeurs saisies à la main par un administrateur sont donc préservées.

## Import manuel d'un export DOAJ

Le pipeline télécharge et importe l'export DOAJ automatiquement. Pour forcer l'import d'un fichier déjà téléchargé (par exemple pour amorcer la base à partir d'un export récupéré à part), `interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni.
