# Chantier — Pays : noms de lieux pour la détection + performances de la phase

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

### 2. Découverte + seed (institutions = universités)
- [x] Constat : les **tokens isolés** singleton-pays captent la **langue** (tout mot français → `fr` dans un corpus francophone), pas le lieu — abandonnés au profit d'**expressions**.
- [x] Première marche : noms d'**universités**, n-grammes singleton-pays autour de « université » / « university » (`universite X`, `university of X`, `X university`, `X university hospital`), dédup suffixe (retire les fragments tronqués à gauche). 4405 expressions, 93 pays. Seedées `kind = 'institution'` via migration `b8e3a1f6d4c2` (SQL pur, reproductible).
- [x] Casse canonicalisée en **minuscule** : `place_name_forms.iso_code` + `publishers.country` étaient les seuls outliers vs `countries.code` / `addresses.countries` / la cascade. Conversions retirées (`detect` n'a plus de `.lower()` par adresse ; OpenAlex enrich lowercase à l'entrée) ; affichage front en MAJ (présentation).
- [x] **2e marche** : mêmes n-grammes d'universités, mais sur les adresses **sans pays à suggestion unique et cohérente** (`cardinality(suggested_countries) = 1`, la suggestion fait foi) → **655 formes inédites**, 63 pays, `kind = 'institution'` (migration `b9d4e7a2f5c8`).
- [ ] Marches suivantes : **villes** (`kind = 'city'`, passe `place` prête à les boucler), codes postaux, autres formes d'universités (universidad / università / universität…).

### 3. Détection des lieux (logique pipeline)
- [x] Passe `detect_place_countries` (automate Aho-Corasick sur `place_name_forms` `kind IN ('institution', 'city')`, match au mot près n'importe où) → `countries` (autoritaire) quand tous les lieux matchés s'accordent ; conflit (pays multiples) → ignoré, laissé à `suggest`. Câblée entre `detect_address_countries` (noms de pays, fin de segment) et `suggest`. Rendement mesuré (institutions seules) : **12 297** adresses résolues (~6% des sans-pays), 72 conflits, 0,7s.

### 4. `suggest` : retry-vides idempotent
- [x] `reset` / `reset_empty` supprimés (scan ~34s en moins). Le mode full (`retry_empty`) réessaie les nouvelles **+ les vides** (`= []`, échecs précédents — au cas où le pool aurait grossi), **sans recalculer les positives** (rarement changeantes, coûteuses : recalculer tout faisait 164k/~160s vs 47k/~55s). Écriture idempotente (`IS DISTINCT FROM`). Incrémental : nouvelles seulement. Attribut de mode `reset_country_suggestions` → `retry_empty_country_suggestions`.

### 5. `refresh_publication_countries` — refresh incrémental
- [x] **Deux flags `countries_dirty`** (migrations `d5b8c3f1e9a2` + `f3a8d2c5e1b7`) : sur `source_authorships` pour les **nouveaux sa** (normalize, défaut `true`), et sur `addresses` pour les **pays changés** (posé **gratuitement** dans l'écriture de `countries` par `write_countries` — même ligne déjà réécrite). Le refresh **dérive** les sa à recalculer par une UNION des deux flags (JOIN, lecture) — **pas de marquage de masse** des sa partagés (une adresse institutionnelle liée à des milliers d'authorships ne déclenche plus des centaines de milliers d'écritures de flag). Recalcule les sa dirty (LEFT JOIN orphelin → NULL, cleanup absorbé), puis sp et publications scopés sur eux, puis purge les deux flags. Le recompute complet (~461s pour **0** changement, mesuré) devient O(ce qui a changé). Split par source supprimé (dirty-scoping borne le volume).

## Questions ouvertes

- **Token vs expression** dans la génération et la détection des villes (précision vs simplicité).
- **Ville → `countries` (auto)** pour les villes très sûres vs **toujours `suggested_countries`** : le risque « Paris, Texas » justifie le défaut prudent, mais certaines villes pourraient être assez univoques dans le périmètre pour écrire `countries` directement.
- **Faux positifs** : un nom de ville présent dans une adresse d'un autre pays. La règle « toujours le même pays dans le corpus » + la curation limitent, sans éliminer.
- **Place de la détection ville** : pass dédiée distincte de `detect`/`suggest`, ou fusion des trois en une passe AC unique sur `place_name_forms` + l'emprunt flou en dernier recours.
- **`refresh_publication_countries`** : où est le coût (~1 min/source), et quelle optimisation (batch par source déjà en place ; index, matérialisation, ou recalcul ciblé sur les adresses modifiées).

## Liens

- État actuel : [`detect_address_countries.py`](../../interfaces/cli/pipeline/detect_address_countries.py), [`suggest_address_countries.py`](../../interfaces/cli/pipeline/suggest_address_countries.py), [`suggest_countries.py`](../../application/pipeline/countries/suggest_countries.py) (`CountrySuggester`), [`countries.py`](../../infrastructure/queries/pipeline/countries.py) (requêtes), [`refresh_publication_countries.py`](../../application/pipeline/countries/refresh_publication_countries.py).
