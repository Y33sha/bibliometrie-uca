uv run python -m interfaces.cli.oneshot.purge_descriptive_page_locations
uv run python -m interfaces.cli.oneshot.canonicalize_hal_location_urls
uv run python -m interfaces.cli.oneshot.clean_source_record_texts
uv run python -m interfaces.cli.oneshot.backfill_best_copy_urls
uv run python -m interfaces.cli.oneshot.recompute_oa_statuses
uv run python -m interfaces.cli.oneshot.rewrite_biblio_journal
uv run python -m interfaces.cli.oneshot.drop_platform_series
uv run python -m interfaces.cli.oneshot.apply_platform_rules
uv run python -m interfaces.cli.oneshot.drop_series_without_issn
uv run python -m interfaces.cli.oneshot.rewrite_publication_dates
uv run python -m interfaces.cli.oneshot.restore_primary_identifiers
uv run python -m interfaces.cli.oneshot.restore_identifiers_from_source_id
uv run python -m interfaces.cli.oneshot.reset_hal_disappearances
uv run python -m interfaces.cli.oneshot.write_source_record_subjects
UPDATE sources.staging SET raw_hash = NULL, last_seen_at = '2000-01-01' WHERE source = 'theses';
UPDATE sources.staging SET last_seen_at = '2000-01-01' WHERE source = 'hal';
INSERT INTO queues.source_record_keys_queue (id)
SELECT DISTINCT source_record_id FROM sources.source_record_identifiers
WHERE id_type = 'doi' AND role <> 'related'
  AND lower(id_value) ~ '^10\.5194/[a-z]+-[0-9]{4}-[0-9]+$'
ON CONFLICT (id) DO UPDATE SET seq = DEFAULT;
uv run python -m interfaces.cli.oneshot.delete_hal_ids_from_dois
uv run python -m interfaces.cli.oneshot.delete_openalex_person_harvest_orphans

# Pipeline
## Extraction
* [ ] Dimensions?; ArXiv, PMC, Pubmed; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS? creuser ISTEX
* [ ] INPI pour les brevets
* [ ] payloads bruts: ne plus faire transiter par la base?
## Suite du traitement
* [ ] normalisation en parallèle de l'extraction?
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer) / annoter un corpus et trouver une bonne fonction de décision
# Données
* [ ] conserver l'historique des structures
* [ ] financements (projets ANR, projets européens)
* [ ] publications fermées, sans localisation éditeur, avec revue OA: chercher des moyens de retrouver les localisations éditeur (URL des revues)
* [ ] OpenAlex: raw affiliation strings qui dérivent de noms de structures HAL: pas de vraies adresses
# UI
## Admin
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA")
* [ ] fusionner structures
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
## Publique
* [ ] page "affiliations divergentes hal": requête incorrecte, capture trop de publis
* [ ] auteur premier, dernier, correspondant: sur les facettes et les stats
* [ ] stats en compte fractionnaire vs compte entier?
* [ ] embargo dans HAL: signaler dans la page publication (cf 165044)
* [ ] liens ISSN: généraliser
### Visualisation
* [ ] taux de collaboration
* [ ] évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* [ ] visualisation des collab avec carte (monde, Europe, France) qui les localise au niveau de leur ville
* [ ] année en cours: diminuer l'opacité

# Cas particuliers, bizarreries à élucider
* 132757 collab Argentine? (il y en a bcp comme ça)
* 165044 et 301756: pourquoi les records openalex fusionnent avec le preprint et pas l'article?
* "How Self-Location Predicts the Degree and Quality of the Felt Sense of Connection" => preprint de ... (DOI non résolu) + lien open access renvoie sur la v1
