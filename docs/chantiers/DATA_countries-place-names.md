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

## Décisions

> Section proposée — à challenger. Seul le Contexte est figé.

- **Table `place_name_forms`** : renommer `country_name_forms` → `place_name_forms` et ajouter une colonne `kind` (`country` | `city`). Même forme (`form_normalized → iso_code`) ; le `kind` porte la priorité (country > city) et la confiance. Alternative écartée : table sœur `city_name_forms` — deux chargements, deux scans, sans bénéfice.
- **Détection unifiée par automate Aho-Corasick** : un seul automate sur toutes les `place_name_forms`, un passage par adresse (comme le matching `structure_name_forms`). Remplace l'extraction du seul dernier segment — une ville peut apparaître n'importe où dans l'adresse. Priorité au nom de pays (autoritaire) sur la ville (heuristique).
- **Confiance** : un match **nom de pays** reste autoritaire → `countries`. Un match **ville** est heuristique → `suggested_countries` (confirmation manuelle), pas d'écrasement direct de `countries` (risque de faux positif type « Paris, Texas »). Une ville alimente donc une *meilleure* suggestion que l'emprunt flou actuel, sans auto-confirmer un FP.
- **Découverte empirique des villes** : depuis les adresses *avec* pays, retenir les tokens apparaissant dans ≥ 10 adresses **et toujours associés au même pays** → candidats. Curation manuelle one-shot pour ne garder que de vrais noms de lieux (écarter les termes génériques qui se trouvent corrélés à un pays dans le corpus).
- **`suggest` : supprimer le reset, recompute-all idempotent.** En mode full, recalculer toutes les cibles éligibles (`countries IS NULL`, len ≥ 5) et n'écrire que les deltas (`suggested_countries IS DISTINCT FROM …`). Élimine le scan de reset (~34s), rafraîchit aussi les suggestions positives contre le pool agrandi, et aligne la phase sur le recalcul idempotent adopté ailleurs.
- **`refresh_publication_countries`** : optimisation étudiée en fin de chantier (piste à instruire, pas encore tranchée).

## Phasage

### 1. Découverte des candidats villes
- Requête de génération (lecture seule) : tokens des `addresses.normalized_text` ayant un pays, fréquence ≥ 10, un seul pays distinct associé. Sortie : `(token, iso_code, fréquence)` triée, pour mesurer le volume et alimenter la curation.
- À décider sur pièces : granularité token seul vs expressions multi-mots (« clermont ferrand », « new york »).

### 2. Curation
- Tri manuel one-shot des candidats : ne garder que de vrais noms de lieux, assembler les expressions multi-mots si retenu.

### 3. Schéma
- Migration : renommer `country_name_forms` → `place_name_forms`, ajouter `kind` (défaut `country` pour l'existant), insérer les villes curées (`kind = city`). Mettre à jour `tables.py` + le snapshot.

### 4. Détection par place names (logique pipeline)
- Passe de détection via automate Aho-Corasick sur `place_name_forms` : pays → `countries`, ville → `suggested_countries`. S'intercale entre `detect` (segment) et `suggest` (flou) — ou les absorbe, à décider.

### 5. `suggest` recompute-all idempotent
- Retirer `reset` / `reset_empty` ; le mode full recalcule toutes les cibles éligibles, écriture idempotente (deltas seulement).

### 6. `refresh_publication_countries` — performances
- Instruire les options (différé).

## Questions ouvertes

- **Token vs expression** dans la génération et la détection des villes (précision vs simplicité).
- **Ville → `countries` (auto)** pour les villes très sûres vs **toujours `suggested_countries`** : le risque « Paris, Texas » justifie le défaut prudent, mais certaines villes pourraient être assez univoques dans le périmètre pour écrire `countries` directement.
- **Faux positifs** : un nom de ville présent dans une adresse d'un autre pays. La règle « toujours le même pays dans le corpus » + la curation limitent, sans éliminer.
- **Place de la détection ville** : pass dédiée distincte de `detect`/`suggest`, ou fusion des trois en une passe AC unique sur `place_name_forms` + l'emprunt flou en dernier recours.
- **`refresh_publication_countries`** : où est le coût (~1 min/source), et quelle optimisation (batch par source déjà en place ; index, matérialisation, ou recalcul ciblé sur les adresses modifiées).

## Liens

- État actuel : [`detect_address_countries.py`](../../interfaces/cli/pipeline/detect_address_countries.py), [`suggest_address_countries.py`](../../interfaces/cli/pipeline/suggest_address_countries.py), [`suggest_countries.py`](../../application/pipeline/countries/suggest_countries.py) (`CountrySuggester`), [`countries.py`](../../infrastructure/queries/pipeline/countries.py) (requêtes), [`refresh_publication_countries.py`](../../application/pipeline/countries/refresh_publication_countries.py).
