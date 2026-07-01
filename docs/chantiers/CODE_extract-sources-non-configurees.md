# Chantier — Skip propre des sources d'extraction non configurées

## Contexte

Lancer le pipeline dans Docker fonctionne (invocation, connexion à la base, exécution des phases). En revanche, une source d'extraction non configurée fait remonter `ExtractionConfigError` jusqu'à `main()` et **tue tout le run**, au lieu de sauter cette seule source et de poursuivre avec les sources configurées.
Sur une base fraîchement seedée, le cas est systématique : `structures.api_ids` est vide (aucun identifiant de structure par source) et les credentials sont des placeholders.

Deux problèmes distincts se combinent :

1. **Absence de mode d'échec propre.** `run_as_phase` laisse volontairement remonter les exceptions à l'orchestrateur (`application/pipeline/extract/base.py`), mais `phase_extract` ne les rattrape pas : `future.result()` re-lève et interrompt la phase entière (`run_pipeline.py`). Une source non configurée devrait être ignorée, pas fatale.
2. **Placeholders de credentials contre-productifs.** `generate_seed` masque les credentials par des chaînes `VOTRE_...` / `votre@email.fr`. Une clé bidon non vide empêche OpenAlex de basculer en polite pool (elle est envoyée à l'API comme une vraie clé), et un faux email polite part vers de vraies API (proscrit : risque de blacklist côté serveur).

## Décisions

### Politique de skip

Une source non configurée est **ignorée avec un avertissement**, apparaît « non configurée » au récap de phase, et les sources configurées continuent.
La politique de skip appartient à l'**orchestrateur** (`run_pipeline.py`), pas aux extracteurs : le CLI standalone d'une source continue, lui, de sortir en erreur (`exit 2`) si on lui demande explicitement une source non configurée.

### Skip vs échec dur

Seule l'**absence de configuration** (`ExtractionConfigError`) est skipée.
Les erreurs réseau/HTTP (DNS, 401, 5xx) restent des échecs durs et bruyants : un credential absent est un fait de configuration, une panne réseau n'en est pas un.

### Configuration requise par source

| Source | Requis pour extraire | Lève déjà `ExtractionConfigError` | À ajouter |
|---|---|---|---|
| HAL | ≥1 collection (`hal_collection` du périmètre) | non | lever si 0 collection (cohérence) |
| theses | ≥1 PPN (`api_ids->'theses'`) | oui | rien |
| OpenAlex | `institution_ids` **et** (clé API **ou** email polite) | sur `institution_ids` seul | lever si ni clé ni email ; ne plus exiger l'email quand une clé est présente |
| WoS | `affiliations` **et** clé API | sur `affiliations` seul | lever si clé absente |
| ScanR | `affiliation_ids` **et** (username + password) | sur `affiliation_ids` seul | lever si credentials absents |

OpenAlex est le seul extracteur à consommer l'email polite ; HAL, theses, WoS et ScanR ne l'utilisent pas.
`get_polite_pool_email` conserve son comportement levant pour les autres consommateurs (Crossref, DataCite, Unpaywall).

### Contrainte d'architecture

`ExtractionConfigError` vit en couche `application` ; les getters de credentials (`get_wos_api_key`…) en couche `infrastructure`.
Les adapters ne peuvent pas importer `application` (règle DDD verrouillée par import-linter).
Les checks credentials restent donc en couche application (`application/pipeline/extract/extract_*.py`), là où vivent déjà les checks d'identifiants de structure, en exposant la présence des credentials via l'objet config renvoyé par l'adapter (comme `affiliations` / `institution_ids` le sont déjà).

### Seed sans placeholders

`generate_seed` pose **NULL** au lieu des placeholders pour les credentials.
NULL est honnête (pas de clé plutôt qu'une clé bidon), permet le polite pool OpenAlex, et évite d'envoyer un faux email à de vraies API.
La documentation d'initialisation cesse de renvoyer aux placeholders et explique le renseignement direct des credentials.

## Phasage

### Phase A — Contrat « source configurée » par extracteur

- [ ] `infrastructure/sources/config.py` : getter email non-levant pour OpenAlex (le levant reste pour Crossref/DataCite/Unpaywall).
- [ ] Adapters openalex/wos/scanr : exposer la présence clé/credentials dans `*ExtractConfig` ; OpenAlex n'exige plus l'email quand une clé est présente.
- [ ] `application/pipeline/extract/extract_openalex.py` : lever `ExtractionConfigError` si ni clé ni email.
- [ ] `application/pipeline/extract/extract_wos.py` : lever si clé absente.
- [ ] `application/pipeline/extract/extract_scanr.py` : lever si credentials absents.
- [ ] HAL : lever `ExtractionConfigError` si aucune collection.

### Phase B — Skip propre dans l'orchestrateur

- [ ] `run_pipeline.py` : importer `ExtractionConfigError` ; rattraper autour de `future.result()` (branche parallèle) et de l'appel HAL (mode daily) → avertissement + source « non configurée » + poursuite.
- [ ] Représentation « non configurée » dans le récap de phase (`metrics.details["table"]`), distincte d'une source à zéro résultat.

### Phase C — Seed sans placeholders

- [ ] `interfaces/cli/dev/generate_seed.py` : credentials → NULL.
- [ ] Régénérer `infrastructure/db/seed.sql`.
- [ ] Docs : retirer la section placeholders / `UPDATE config` de `docs/exploitation/02-initialisation-base.md` ; documenter le skip des sources aux credentials NULL et le renseignement direct.

### Phase D — Tests

- [ ] Test de non-régression : run `extract` avec des sources non configurées → celles-ci skipées, les configurées aboutissent.
- [ ] Test par source du contrat de configuration (OpenAlex tolérant clé ou email ; WoS et ScanR credentials requis ; HAL collections requises).

## Questions ouvertes

- Représentation exacte de « non configurée » dans le récap de phase (colonne statut de la table par source, ou ligne dédiée) — à trancher à l'implémentation, en cohérence avec le chantier [Observabilité du pipeline](CODE_observabilite-pipeline.md).
