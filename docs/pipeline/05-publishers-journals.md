# Enrichissement des référentiels publishers et journals

Phase `publishers_journals` : enrichit les **référentiels** `journals` (revues) et `publishers` (éditeurs) à partir de sources externes, après leur création initiale en phase [normalize](03-normalize.md).

Six sous-étapes enchaînées. La première (`resolve_doi_prefixes`) s'exécute à chaque lancement du pipeline ; les cinq autres ne tournent que lorsque l'enrichissement des référentiels est activé pour le mode courant (drapeau de politique `run_journal_enrichment`, vrai en mode `full`).

| Sous-étape | Source externe | Ce qu'elle renseigne | Quand |
|---|---|---|---|
| `resolve_doi_prefixes` | Crossref `/prefixes/{prefix}` + DataCite `/dois?prefix=` | `doi_prefixes` : pour chaque préfixe DOI, son agence d'enregistrement et l'éditeur (Crossref) ou l'entrepôt (DataCite) qui le détient | toujours |
| `enrich_journals_from_openalex` | [OpenAlex Sources](../sources/03-openalex.md) | `journals` : type de revue, montant et devise des frais de publication (APC) | mode `full` |
| `enrich_journals_from_doaj` | export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj) | `journals` : fiche DOAJ complète (`doaj_payload`) et appartenance au DOAJ (`is_in_doaj`) | mode `full` |
| `enrich_publishers_from_openalex` | [OpenAlex Publishers](../sources/03-openalex.md) | `publishers` : pays (ISO-2) et identifiant ROR | mode `full` |
| `enrich_publishers_from_crossref_members` | [Crossref Members](../sources/06-crossref.md) | `publishers` : pays (rattrapage des éditeurs sans pays après OpenAlex) | mode `full` |
| `enrich_publishers_from_ror` | [ROR](../sources/09-sources-supplementaires.md#ror) | `publishers` : type d'éditeur (`commercial`, `academic_institution`, `learned_society`, `repository`) | mode `full` |

## DOAJ : import par export complet

Le DOAJ publie chaque semaine un export complet de son catalogue, sous forme d'un fichier CSV. La sous-étape télécharge cet export, puis met à jour toutes les revues en une passe, par appariement sur l'ISSN : elle écrit la fiche DOAJ (`doaj_payload`) et le drapeau `is_in_doaj`.

Pour `is_in_doaj`, le DOAJ fait autorité : le drapeau est remis à `false` partout, puis remis à `true` pour les seules revues présentes dans l'export. L'export n'est re-téléchargé qu'au plus une fois tous les 30 jours (il est conservé dans `data/doaj/`) ; tant que le dernier import est plus récent que ce seuil, la sous-étape est entièrement sautée.

## Idempotence

Chaque sous-étape est incrémentale — filtres d'éligibilité :

- `resolve_doi_prefixes` : préfixes encore absents de `doi_prefixes`.
- `enrich_journals_from_openalex` : revues ayant un `openalex_id` et un type encore inconnu (`journal_type = 'unknown'`).
- `enrich_journals_from_doaj` : déclenché par l'âge du dernier import (voir ci-dessus), et non par un filtre revue par revue.
- `enrich_publishers_from_openalex` : éditeurs ayant un `openalex_id` mais à qui il manque le pays ou le ROR.
- `enrich_publishers_from_crossref_members` : éditeurs sans pays, reliés à un identifiant de membre Crossref via `doi_prefixes`.
- `enrich_publishers_from_ror` : éditeurs ayant un ROR et un type encore inconnu (`publisher_type = 'unknown'`).

Politique d'écrasement : une valeur n'est posée que si la cible est vide. Les valeurs saisies à la main par un administrateur sont donc préservées.

## Import manuel d'un export DOAJ

Le pipeline télécharge et importe l'export DOAJ automatiquement. Pour forcer l'import d'un fichier déjà téléchargé (par exemple pour amorcer la base à partir d'un export récupéré à part), `interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni.
