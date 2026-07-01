# Chantier — Skip propre des sources d'API tierces non configurées

## Contexte

Le pipeline interroge plusieurs API tierces, à plusieurs phases : extraction bulk (HAL, OpenAlex, WoS, ScanR, theses.fr), cross-imports par DOI et hal-id, rafraîchissement des documents stale, enrichissements (journaux OpenAlex, préfixes DOI Crossref/DataCite, statut open access Unpaywall). Chacun de ces accès dépend d'une configuration : credentials d'API (clé, basic auth, email polite pool) et, pour l'extraction bulk seulement, un périmètre d'interrogation (collections HAL, identifiants d'institution ou d'affiliation, PPN d'établissement).

Sur une base fraîchement seedée, une partie de cette configuration manque : les credentials valent `NULL` tant que l'exploitant ne les renseigne pas. Le comportement attendu est **uniforme** : un accès dont la configuration manque est **sauté avec un avertissement**, sans interrompre le run, quelle que soit la phase. Les accès configurés aboutissent.

Deux écarts à corriger par rapport à cet objectif :

1. **Traitement hétérogène selon la phase.** L'extraction bulk sait sauter une source non configurée, mais les autres phases ne le font pas : le cross-import ScanR tire une requête sans credentials puis avale le 401 en résultat vide, et les enrichissements Crossref/DataCite/Unpaywall/OpenAlex lèvent une exception dure sur email absent. Le même fait (« source non configurée ») produit trois comportements différents.
2. **Placeholders de credentials contre-productifs dans le seed.** Une clé bidon non vide est envoyée à l'API comme une vraie clé (échec d'authentification), et un faux email polite pool part vers de vraies API (risque de blacklist côté serveur).

## Décisions

### Skip propre, harmonisé sur toutes les phases

Un accès à une API tierce dont la configuration manque est **ignoré avec un avertissement** ; les accès configurés continuent. La règle vaut pour toutes les phases qui interrogent une API : extraction, cross-imports, refresh stale, enrichissements. Le CLI standalone d'une source garde, lui, sa sortie en erreur (`exit 2`) quand on lui demande explicitement une source non configurée.

### Détecteur central de configuration (source unique de vérité)

La connaissance « credentials présents pour la source X » vit à **un seul endroit**, en couche `infrastructure` (`infrastructure/sources/config.py`) : une fonction `source_credentials_missing(conn, source) -> str | None` renvoie le motif d'absence (message lisible) ou `None` si la source est utilisable. Tous les appelants la consultent ; aucune logique de présence de credentials n'est dupliquée par phase.

### Périmètre d'interrogation ⊥ credentials

L'extraction bulk exige **en plus** un périmètre d'interrogation (collections HAL, `institution_ids` OpenAlex, `affiliations` WoS/ScanR, PPN theses) : ce contrôle reste propre à l'extraction. Le cross-import et les enrichissements interrogent par identifiant (DOI, hal-id) sans périmètre : ils ne vérifient que les credentials.

### Email polite pool = credential

`polite_pool_email` est traité comme un credential : son absence **saute** les accès qui en dépendent (Crossref, DataCite, Unpaywall, et OpenAlex quand aucune clé API n'est configurée), au lieu de lever une exception dure. Renseigner un email ne coûte rien et rend tous ces accès disponibles ; ne pas en avoir n'empêche pas le run d'aboutir.

### Skip vs échec dur

Seule l'**absence de configuration** est sautée. Une erreur réseau/HTTP survenant alors que les credentials **sont** présents (401 sur clé invalide, 5xx, DNS) reste un échec dur et bruyant : un credential absent est un fait de configuration détecté en amont, une panne ou un credential erroné n'en est pas un. Le gate en amont supprime le cas « requête tirée sans credentials » ; le rattrapage d'erreur HTTP des adapters ne couvre plus que le transitoire.

### Signalement d'un accès sauté

Un accès sauté remonte par le **canal des signaux** de `PhaseMetrics` (celui du circuit-breaker) : un `Signal` de niveau `warning`, `code = "source_unconfigured"`, attaché à la `PhaseMetrics` de la phase. Le point de la phase passe en **ambre** (dérivation `status = warning if signals else ok`) et le motif s'affiche au détail. Le rouge reste réservé à une phase interrompue par une exception. La table par source ne liste que les accès ayant tourné.

### Contrainte d'architecture

`ExtractionConfigError` et les orchestrateurs d'extraction vivent en couche `application`, qui ne peut pas importer `infrastructure` (règle DDD verrouillée). L'extraction consulte donc le détecteur central **via l'adapter** : l'adapter (infrastructure) appelle `source_credentials_missing` et expose le motif dans l'objet config renvoyé ; l'orchestrateur (application) lève `ExtractionConfigError` sur ce motif. Le cross-import, le refresh stale et les enrichissements sont orchestrés dans `run_pipeline.py` — composition root, qui importe librement l'infrastructure — et appellent le détecteur directement.

### Configuration requise par source

| Source | Credentials (tous accès) | Périmètre (extraction bulk seulement) |
|---|---|---|
| HAL | aucun (API publique) | ≥1 collection (`hal_collection` du périmètre) |
| theses.fr | aucun (API publique) | ≥1 PPN (`api_ids->'theses'`) |
| OpenAlex | clé API **ou** email polite pool | `institution_ids` |
| WoS | clé API | `affiliations` |
| ScanR | username + password | `affiliation_ids` |
| Crossref | email polite pool | — |
| DataCite | email polite pool | — |
| Unpaywall | email polite pool | — |

DOI.org (résolution des Registration Agencies) et DOAJ sont des API publiques sans credential : aucun gate.

### Seed sans placeholders

`generate_seed` pose `NULL` au lieu des placeholders pour les credentials. `NULL` est honnête (pas de clé plutôt qu'une clé bidon), permet le polite pool OpenAlex par email, et évite d'envoyer un faux email à de vraies API. La documentation d'initialisation explique le renseignement direct des credentials et le skip des sources laissées à `NULL`.

## Phasage

### Phase 1 — Extraction : contrat de configuration et skip propre

- [x] `infrastructure/sources/config.py` : getter email non-levant pour OpenAlex (le levant reste, à ce stade, pour Crossref/DataCite/Unpaywall).
- [x] Adapters openalex/wos/scanr : exposer la présence des credentials dans `*ExtractConfig` ; OpenAlex n'exige plus l'email quand une clé est présente.
- [x] Orchestrateurs openalex/wos/scanr/hal : lever `ExtractionConfigError` sur credentials ou périmètre absents.
- [x] `run_pipeline.py` : rattraper `ExtractionConfigError` (branche parallèle et branche HAL incrémentale) → signal `source_unconfigured`, source sautée, poursuite.
- [x] Tests : skip d'une source non configurée (les configurées aboutissent) ; contrat par source.

### Phase 2 — Seed sans placeholders

- [x] `interfaces/cli/dev/generate_seed.py` : credentials → `NULL`.
- [x] Régénérer `infrastructure/db/seed.sql`.
- [x] Docs : `docs/exploitation/02-initialisation-base.md` documente le skip des sources aux credentials `NULL` et le renseignement direct.

### Phase 3 — Détecteur central de configuration par source (DRY)

- [x] `infrastructure/sources/config.py` : `source_credentials_missing(conn, source) -> str | None`, seule source de vérité de la présence des credentials par source (openalex : clé ou email ; wos : clé ; scanr : user+pwd ; crossref/datacite/unpaywall : email ; hal/theses : aucun).
- [x] Basculer les adapters d'extraction dessus : `*ExtractConfig` porte le motif d'absence (remplace les booléens `has_api_key` / `has_polite_email` / `has_credentials`) ; les orchestrateurs lèvent `ExtractionConfigError` sur ce motif (le contrôle de périmètre leur reste propre).

### Phase 4 — Cross-imports et refresh stale : gate harmonisé

- [ ] `run_pipeline.py` : avant de tirer une requête, `phase_cross_imports` (cibles `fetch_missing_doi`) et `phase_refresh_stale` sautent une source dont `source_credentials_missing` renvoie un motif → signal `source_unconfigured`, poursuite.
- [ ] Adapter ScanR `fetch_missing_doi` : ne plus avaler un 401 en résultat vide (le gate amont supprime le cas « sans credentials » ; une erreur d'authentification credentials présents redevient dure, comme pour WoS).
- [ ] Tests : cible non configurée sautée, cibles configurées interrogées.

### Phase 5 — Enrichissements : email requis, gate harmonisé

- [ ] `run_pipeline.py` : `enrich_journals_from_openalex` (openalex), `resolve_doi_prefixes` (crossref/datacite) et `oa_status` (unpaywall) sautent proprement quand `source_credentials_missing` renvoie un motif, au lieu de lever sur email absent. `get_polite_pool_email` (levant) est remplacé par le gate dans ces chemins.
- [ ] Tests : enrichissement sauté sur email absent, exécuté sinon.

## Questions ouvertes

- **`get_polite_pool_email` (levant) résiduel.** Une fois les phases pipeline basculées sur le gate, ne restent appelants levants que des CLI oneshot/maintenance (hors pipeline), où une sortie en erreur est acceptable. À confirmer au cas par cas plutôt qu'en masse.
