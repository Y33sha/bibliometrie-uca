# Chantier — Adresses → pays : détection, suggestion et performances de la cascade

Commencé le 2026-06-11

## Contexte

La phase `countries` du pipeline dérive le pays de chaque adresse, puis propage en cascade vers les authorships, source_publications et publications. Trois étapes :

1. **`detect_address_countries`** — extrait le **dernier segment** de l'adresse (après la dernière virgule), le normalise, et le cherche dans `country_name_forms` (`form_normalized → iso_code`, exact). Match → écrit directement `addresses.countries` (haute confiance, autoritaire). Rapide.
2. **`suggest_address_countries`** — pour les adresses sans pays après detect, cherche dans le pool des adresses *avec* pays celles dont le `normalized_text` contient la cible comme sous-chaîne, et retient le ou les pays les plus fréquents. Écrit `addresses.suggested_countries` (confirmation manuelle attendue via l'admin). Désormais via un automate Aho-Corasick inversé (~30s sur le stock complet).
3. **`refresh_publication_countries`** — recalcule les caches dénormalisés `source_authorships.countries` → `source_publications.countries` → `publications.countries` depuis `addresses.countries`.

`country_name_forms` contient ~317 formes (noms de pays dans plusieurs langues, codes ISO).

Deux limites motivent ce chantier :

- **Couverture de la détection.** `detect` ne reconnaît que les adresses dont le dernier segment est un nom de pays connu. Une adresse finissant par une ville et un code postal sans pays (fréquent) tombe dans `suggest`, qui n'est qu'une heuristique floue (« emprunter le pays d'une adresse qui me contient »). Un dictionnaire de **noms de lieux** (villes) permettrait une détection déterministe « clermont ferrand → FR », réduisant le résidu envoyé à `suggest` et améliorant la qualité.
- **Performances résiduelles.** `suggest` est désormais rapide, mais le mode full le précède d'un `reset` des suggestions vides qui scanne toute la table `addresses` (~34s d'overhead). Et `refresh_publication_countries` prend ~1 min par source.

## Constat de découverte (2026-06-11)

Lecture seule sur la base de prod, avant de figer le critère de génération.

- **Les adresses sans pays sont des noms d'institutions nus**, pas des « ville + code postal » : labos, universités, ministères, UMR sans ville ni pays (« Institut de Chimie - CNRS Chimie », « Laboratoire Paul Painlevé - UMR 8524 », « Université de Liège » → BE). Le `suggest` flou les résout déjà majoritairement (`['fr']`) ; `place_name_forms` apporte le **déterminisme** (règle indépendante du pool) et l'**autorité** (`countries`, plus de confirmation manuelle).
- **Le critère « token singleton-pays » capture la langue, pas le lieu** : dans un corpus francophone, tout mot français est singleton-FR. Le haut du classement par utilité mêle bruit (mots français `personnes`/`emploi`, prénoms `stéphane`) et signal institutionnel réel (hôpitaux `dupuytren`/`minjoz`/`bergonié`, marqueurs `umr`/`cnrs`). La curation sépare les deux.
- **Signal propre à part : les codes postaux** (tokens numériques singleton-pays, `63000`/`94000` → FR), non ambigus, sans confusion de langue.
- ~3 824 candidats au seuil 10 (dont 548 numériques) — volume à réduire par la curation ciblée sur l'utilité.

## Décisions

> Section proposée — à challenger. Seul le Contexte est figé.

- **Table `place_name_forms`** : renommer `country_name_forms` → `place_name_forms` et ajouter une colonne `kind` (`country` | `place`, `place` couvrant ville / institution / code postal). Même forme (`form_normalized → iso_code`) ; le `kind` porte la règle de détection. Alternative écartée : table sœur — deux chargements, deux scans, sans bénéfice.
- **Détection unifiée par automate Aho-Corasick** : un seul automate sur toutes les `place_name_forms`, un passage par adresse (comme le matching `structure_name_forms`). Remplace l'extraction du seul dernier segment.
- **Place / institution autoritaires → `countries`**, détectées **n'importe où** dans l'adresse. Le risque « Paris, Texas » est faible sur des adresses **institutionnelles** (une université à Paris-Texas est improbable ; au besoin on s'appuie sur des noms d'institutions univoques, « Panthéon-Sorbonne → FR »). Un **nom de pays** écrit aussi `countries`, mais **en fin d'adresse seulement** — sinon on matcherait un pays présent dans un nom d'institution.
- **Signal institutionnel, pas toponymique** (cf. Constat de découverte) : les adresses sans pays sont des noms d'institutions nus (labos, universités, ministères), résolus par les marqueurs du système de recherche français (`cnrs`, `umr`, `inserm`, `cea`, `insa`, `ulr`…), des noms propres d'institutions, et les **codes postaux**. Les villes restent utiles quand présentes.
- **Découverte empirique + curation** : depuis les adresses *avec* pays, tokens singleton-pays au-dessus d'un seuil de fréquence → candidats classés par **utilité** (présence dans les adresses *sans* pays). Aucun filtre purement statistique ne sépare un lieu/une institution (`clermont`, `umr`) d'un mot de langue (`personnes`, `emploi`) — tous singleton-FR dans un corpus francophone, et monter le seuil garde les mots courants en perdant les lieux rares. La **curation manuelle one-shot est donc indispensable** : garder lieux/institutions/codes postaux fiables, écarter mots de langue et noms de personnes. Priorité à l'utilité, pas à l'exhaustivité. **Langue → pays écartée** (risque francophone-hors-France BE/CH/QC).
- **`suggest` : supprimer le reset, recompute-all idempotent.** En mode full, recalculer toutes les cibles éligibles (`countries IS NULL`, len ≥ 5) et n'écrire que les deltas (`suggested_countries IS DISTINCT FROM …`). Élimine le scan de reset (~34s), rafraîchit aussi les suggestions positives contre le pool agrandi, et aligne la phase sur le recalcul idempotent adopté ailleurs.
- **`refresh_publication_countries`** : optimisation étudiée en fin de chantier (piste à instruire, pas encore tranchée).

## Phasage

### 1. Schéma + bascule des consommateurs existants
- [x] Migration `c3e9b1f7a4d2` : rename `country_name_forms` → `place_name_forms` (+ séquence, contraintes, index), colonne `kind` (`country` | `place`, défaut `country`). `tables.py`, `seed.sql`, `generate_seed` (spec + `kind`).
- [x] Consommateurs existants câblés sur `place_name_forms` (`kind = 'country'`) : `detect_address_countries`, résolution nom-de-pays → ISO côté publishers (crossref enrich + audit oneshot).

### 2. Formes de lieux : ROR + complément empirique
- [x] **Casse minuscule canonique** des codes pays : `place_name_forms.iso_code` et `publishers.country` (seuls outliers) alignés sur `countries.code` / `addresses.countries` / la cascade ; conversions `.lower()` retirées (`detect` n'écrit plus par adresse, OpenAlex enrich lowercase à l'entrée), affichage front en MAJ.
- [x] **Institutions via ROR** (autoritaire) : oneshot `seed_place_names_from_ror`. `--build` aplatit le dump ROR v2.8 épinglé (`names[].value × locations[].geonames_details.country_code`), garde les formes **mono-pays, hors acronymes / numériques / < 6 caractères** (faux positifs), → CSV gitignoré ; le seed insère `kind = 'institution'` (`ON CONFLICT DO NOTHING`). Puis `prune_place_names` supprime les formes **absentes du corpus** (scan de **toutes** les adresses ; celles présentes dans des adresses déjà résolues resservent au full rerun) → ~**24 k institutions** pertinentes.
- [x] **Complément empirique** : formes présentes dans les adresses mais **absentes de ROR** (n-grammes singleton-pays, hors France trop bruitée), curées — exclusion des formes déjà couvertes par une forme ROR du même pays, dédup par inclusion (garde la plus courte), rognage des mots de bord génériques (connecteurs, champs, structure), curation manuelle — réintégrées via `seed --csv` (~1 k).
- [x] **Villes** (`kind = 'city'`) : extraction des formes entre **crochets droits** des adresses brutes (`[Bremen]`, `[Santiago]`…), pays dérivé par singleton-pays sur les adresses déjà résolues, curation manuelle (composés ville+pays, institutions glissées) → 186 villes + 36 institutions seedées (`seed --csv` avec colonne `kind`) ; **11,8 k adresses résolues** sur 72 k restantes.
- [x] **Structures HAL** (`seed_place_names_from_hal`) : complète ROR avec les noms de structures du référentiel HAL référencés par le corpus. On interroge l'API ref/structure **par `docid`** sur les ~43 k structures réellement présentes dans `source_structures` (pas les 610 k fiches), **sans filtre `valid_s`** (35 % du corpus est OLD/INCOMING mais porte un pays valide). Champ `name_s` = le `StructNom` que `normalize_hal` met dans `addresses` (vérifié, `normalize_text` identique), pays `country_s` ; garde-fou **mono-pays** (622 noms multi-pays écartés). → **31,6 k formes inédites** (`institution` 25 k → 57 k).
- [ ] Suites (mêmes outils) : **acronymes** ROR (`cnrs`/`mit`… avec filtre anti-mots-courants) et **codes postaux** (`kind = 'postal_code'`).

### 3. Détection des lieux (logique pipeline)
- [x] Passe `detect_place_countries` (automate Aho-Corasick sur `place_name_forms` `kind IN ('institution', 'city')`, match au mot près n'importe où) → `countries` (autoritaire) quand tous les lieux matchés s'accordent ; conflit (pays multiples) → ignoré, laissé à `suggest`. Câblée entre `detect_address_countries` (noms de pays, fin de segment) et `suggest`. Rendement mesuré (institutions seules) : **12 297** adresses résolues (~6% des sans-pays), 72 conflits, 0,7s.

### 4. `suggest` : retry-vides idempotent
- [x] `reset` / `reset_empty` supprimés (scan ~34s en moins). Le mode full (`retry_empty`) réessaie les nouvelles **+ les vides** (`= []`, échecs précédents — au cas où le pool aurait grossi), **sans recalculer les positives** (rarement changeantes, coûteuses : recalculer tout faisait 164k/~160s vs 47k/~55s). Écriture idempotente (`IS DISTINCT FROM`). Incrémental : nouvelles seulement. Attribut de mode `reset_country_suggestions` → `retry_empty_country_suggestions`.

### 5. `refresh_publication_countries` — refresh incrémental
- [x] **Deux flags `countries_dirty`** (migrations `d5b8c3f1e9a2` + `f3a8d2c5e1b7`) : sur `source_authorships` pour les **nouveaux sa** (normalize, défaut `true`), et sur `addresses` pour les **pays changés** (posé **gratuitement** dans l'écriture de `countries` par `write_countries` — même ligne déjà réécrite). Le refresh **dérive** les sa à recalculer par une UNION des deux flags (JOIN, lecture) — **pas de marquage de masse** des sa partagés (une adresse institutionnelle liée à des milliers d'authorships ne déclenche plus des centaines de milliers d'écritures de flag). Recalcule les sa dirty (LEFT JOIN orphelin → NULL, cleanup absorbé), puis sp et publications scopés sur eux, puis purge les deux flags. Le recompute complet (~461s pour **0** changement, mesuré) devient O(ce qui a changé). Split par source supprimé (dirty-scoping borne le volume).

### 6. `suggest` : matching flou au lieu de la sous-chaîne exacte — écartée (gain trop faible)

- [ ] **Écartée** — coût mesuré OK mais rendement trop faible (~23 % de suggestions, non autoritaires, sur le résidu le plus sale). Détail ci-dessous ; à reconsidérer si le résidu grossit.

Idée : remplacer la sous-chaîne exacte d'`suggest` (Aho-Corasick) par un matching flou trigramme (`pg_trgm`, `:cible <% normalized_text`, garde consensus) pour rattraper les quasi-identiques que l'exact rate (typos `Clermont Ferand`, espacement, ordre des mots, abréviations).

Mesuré (base chaude, seuil 0.7) : l'index `idx_addresses_normalized_text_trgm` est bien mobilisé, **~140 ms/cible** (médiane 91 ms) ; le rattrapage des ~6,5k résiduelles tient en ~15 min mono-thread, ~3-4 min parallélisé — donc le **coût n'est pas l'obstacle**. C'est le **rendement** qui est trop faible : **66 %** des résiduelles ne matchent rien (les adresses les plus sales), 11 % donnent un conflit multi-pays (rien écrit) ; le flou ne produit que ~23 % de suggestions (~1,5k), **non autoritaires** (confirmation manuelle), sur le résidu le plus difficile.

**Décision : écartée.** Le flou est intrinsèquement par-cible (vs le passage unique de l'Aho-Corasick) et son gain (~1,5k suggestions à confirmer) ne justifie ni le coût par-cible en mode full ni la complexité ajoutée. À reconsidérer seulement si le résidu grossit nettement.

### 7. Cascade `refresh_publication_countries` : matérialiser l'ensemble dirty une fois + fusionner le clear — no-go (non prioritaire)

- [ ] **No-go** — perf pure, gain **uniquement sur les gros reruns complets** (3,46M sa dirty) ; l'incrémental de la phase 5 borne déjà le cas normal (daily/weekly), donc aucun gain au quotidien. L'inefficience (double-write + CTE `_DIRTY_SA` recalculée 3×) **existe toujours** dans le code (vérifié 2026-06-19) et l'analyse ci-dessous reste valable — à reprendre seulement si les reruns complets deviennent fréquents et que le `clear` ~15 min gêne.

La cascade (`refresh_sa_countries` → `refresh_address_source_countries` → `refresh_publication_countries` → `clear_countries_dirty`) paie deux coûts cachés sur un rerun complet, observés sur un run à **3,46M `source_authorships` dirty** (`refresh_sa` ~1934s, `clear` ~15 min) :

- **Double-write.** L'étape 1 réécrit les lignes dont `countries` change (~3,18M) ; le `clear` final réécrit **toutes** les lignes dirty (3,46M) pour repasser `countries_dirty = false`. Les lignes changées sont donc réécrites deux fois (pays, puis flag) → ~6,6M écritures au lieu de ~3,46M.
- **CTE recalculée 3×.** Les trois étapes re-dérivent le même ensemble dirty depuis la CTE `_DIRTY_SA` (scan des 3,46M lignes flaguées), une fois chacune.

On ne peut **pas** fusionner naïvement `countries_dirty = false` dans l'étape 1 : les étapes 2 et 3 re-calculent `_DIRTY_SA` depuis le flag pour trouver les `source_publications` / `publications` à rafraîchir — effacer le flag en étape 1 leur ferait voir un ensemble vide. Le flag doit survivre jusqu'à la fin des trois passes ; c'est pour ça que le `clear` est en étape 4.

**Piste** : matérialiser l'ensemble dirty **une seule fois** au début (table temporaire indexée), pointer les trois étapes dessus au lieu du flag, fusionner `countries_dirty = false` dans l'UPDATE de l'étape 1, et supprimer le `clear` séparé sur `source_authorships` (le clear `addresses`, ~1800 lignes, reste trivial). Gain : écritures `source_authorships` ~6,6M → ~3,46M, et deux scans de 3,46M en moins. En fusionnant, le garde `countries IS DISTINCT FROM` de l'étape 1 perd son effet (le flag bascule sur toutes les lignes dirty) — on réécrit ~284k lignes « pays inchangé » en plus à l'étape 1, négligeable face au `clear` supprimé. Sans effet sur les runs incrémentaux (delta petit) ; gain entièrement sur les gros reruns. À cadrer aussi : l'observabilité (les étapes 3 et 4 n'ont aucun log propre — un `clear` de 15 min se lit comme « publications qui traîne »), donc loguer la durée de chaque étape au passage.

## Questions ouvertes

- **Token vs expression** dans la génération et la détection des villes (précision vs simplicité).
- **Ville → `countries` (auto)** pour les villes très sûres vs **toujours `suggested_countries`** : le risque « Paris, Texas » justifie le défaut prudent, mais certaines villes pourraient être assez univoques dans le périmètre pour écrire `countries` directement.
- **Faux positifs** : un nom de ville présent dans une adresse d'un autre pays. La règle « toujours le même pays dans le corpus » + la curation limitent, sans éliminer.
- **Place de la détection ville** : pass dédiée distincte de `detect`/`suggest`, ou fusion des trois en une passe AC unique sur `place_name_forms` + l'emprunt flou en dernier recours.
- **`refresh_publication_countries`** : où est le coût (~1 min/source), et quelle optimisation (batch par source déjà en place ; index, matérialisation, ou recalcul ciblé sur les adresses modifiées).

## Liens

- État actuel : [`detect_address_countries.py`](../../interfaces/cli/pipeline/detect_address_countries.py), [`suggest_address_countries.py`](../../interfaces/cli/pipeline/suggest_address_countries.py), [`suggest_countries.py`](../../application/pipeline/countries/suggest_countries.py) (`CountrySuggester`), [`countries.py`](../../infrastructure/queries/pipeline/countries.py) (requêtes), [`refresh_publication_countries.py`](../../application/pipeline/countries/refresh_publication_countries.py).
