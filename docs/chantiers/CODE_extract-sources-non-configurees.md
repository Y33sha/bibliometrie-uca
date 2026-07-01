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

### Signalement d'une source sautée

Une source sautée remonte par le **canal des signaux** de `PhaseMetrics` (celui qu'emprunte déjà le circuit-breaker via `_signal_if_tripped`), pas par une représentation ad hoc : l'`except ExtractionConfigError` de `phase_extract` attache à la `PhaseMetrics` de la phase un `Signal` de niveau `warning` (`code = "source_unconfigured"`, message « <source> non configurée — sautée »). Le point de la phase passe en **ambre** et le motif s'affiche au drill-down.
Warning et non erreur : le rouge est réservé à une phase interrompue par une exception (le run s'arrête là), et « source indisponible » relève de l'ambre dans la légende du ruban. Une source sautée n'interrompt pas le run — la phase se termine avec les sources configurées. La dérivation `status = warning if signals else ok` fait passer la phase en ambre sans logique de statut supplémentaire.
La table par source ne liste que les sources ayant tourné : une source sautée n'y produit aucune ligne, ce qui la distingue d'une source à zéro résultat (ligne de table à zéros).

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

### Phase 1 — Contrat « source configurée » par extracteur

- [x] `infrastructure/sources/config.py` : getter email non-levant pour OpenAlex (le levant reste pour Crossref/DataCite/Unpaywall).
- [x] Adapters openalex/wos/scanr : exposer la présence clé/credentials dans `*ExtractConfig` ; OpenAlex n'exige plus l'email quand une clé est présente.
- [x] `application/pipeline/extract/extract_openalex.py` : lever `ExtractionConfigError` si ni clé ni email.
- [x] `application/pipeline/extract/extract_wos.py` : lever si clé absente.
- [x] `application/pipeline/extract/extract_scanr.py` : lever si credentials absents.
- [x] HAL : lever `ExtractionConfigError` si aucune collection.

### Phase 2 — Skip propre dans l'orchestrateur

- [x] `run_pipeline.py` : importer `ExtractionConfigError` ; rattraper autour de `future.result()` (branche parallèle) et de l'appel HAL (mode daily) → avertissement + source « non configurée » + poursuite.
- [x] Signal `warning` (`code = "source_unconfigured"`) attaché à la `PhaseMetrics` de `extract` pour chaque source sautée, dans l'`except ExtractionConfigError` de `phase_extract` → point ambre + motif au drill-down. La table par source ne liste que les sources ayant tourné.

### Phase 3 — Seed sans placeholders

- [x] `interfaces/cli/dev/generate_seed.py` : credentials → NULL.
- [x] Régénérer `infrastructure/db/seed.sql`.
- [x] Docs : retirer la section placeholders / `UPDATE config` de `docs/exploitation/02-initialisation-base.md` ; documenter le skip des sources aux credentials NULL et le renseignement direct.

### Phase 4 — Tests

- [ ] Test de non-régression : run `extract` avec des sources non configurées → celles-ci skipées, les configurées aboutissent.
- [ ] Test par source du contrat de configuration (OpenAlex tolérant clé ou email ; WoS et ScanR credentials requis ; HAL collections requises).
