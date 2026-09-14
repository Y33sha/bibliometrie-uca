# Chantier — Langues : référentiel, normalisation et facette

## Contexte

**Le champ `language` n'est pas normalisé.** `source_publications.language` porte la valeur donnée par la source. `publications.language` reprend la première valeur non nulle dans l'ordre de priorité des sources (`domain/publications/aggregation.py`). Seul le volet des publications de l'administration l'affiche.

**Chaque source a sa forme** (base locale, 2026-09-13) :
- HAL (`language_s`), OpenAlex, Crossref et DataCite donnent surtout des codes ISO 639-1 à deux lettres (`en`, `fr`…). Crossref et DataCite les passent en minuscules.
- Des codes à trois lettres s'y mêlent : `eng` et `fra` (ISO 639-2), `grc`, `ang`, `ckb`, `ceb` (langues sans code à deux lettres). S'y ajoutent des valeurs douteuses : `enc`, `qno`, `ng`, `ie`.
- HAL écrit `und` (langue indéterminée) pour 56 enregistrements.
- WoS donne le nom anglais de la langue : `English`, `French`, `Spanish`.
- ScanR ne donne pas de langue.
- theses.fr ne la donne pas dans l'API de recherche, que le pipeline moissonne. Seul le détail d'une thèse (`/api/v1/theses/these/{nnt}`) porte un champ `langues`, qui est une liste : `["en","fr"]` pour `2022UCFAC034`, dont le titre principal est en anglais.

**La publication hérite du mélange.** `publications.language` compte `English` (75), `French` (23), `und` (37), `eng` et `fra` à côté des codes à deux lettres.

**OpenAlex attribue le letton (`lv`) à 821 enregistrements**, quand aucune autre source n'en compte plus de deux.

**Le type de document sert de précédent.** Les normaliseurs écrivent le type donné par la source. La passe unaire de la phase `metadata_correction` le ramène au vocabulaire du projet (`map_doc_type`), écrit le résultat dans la colonne et garde la valeur source dans `raw_metadata.doc_type`. Elle repart de la valeur source à chaque exécution, sur toutes les `source_publications`. `source_publications.doc_type` reste du texte ; `publications.doc_type` est typé.

**Le référentiel des pays sert de modèle** : table `countries (code, name)`, formes de noms dans `place_name_forms`, chargées par le seed commun, facette « Pays » des listes de publications.

## Décisions

- **Une table `languages (code, name)`** sert de référentiel. Le code est celui d'ISO 639-1 quand il existe, celui d'ISO 639-3 sinon, comme dans BCP 47. Les libellés sont en français, pour l'affichage.
- **Une table `language_forms (form_normalized, language_code)`** porte les formes sous lesquelles les sources désignent une langue : code à deux lettres, codes ISO 639-3 et ISO 639-2 bibliographique (`fra`, `fre`), nom anglais (`English`), variantes (`Greek`). Reconnaître une forme de plus revient à insérer une ligne.
- **La migration remplit les deux tables, le seed commun les recharge.** La base de test, créée par les seules migrations, dispose ainsi du référentiel.
- **Pas de clé étrangère des publications vers `languages`.** Le seed vide la table avant de la remplir. La normalisation ne produit que des codes du référentiel.
- **La passe unaire de `metadata_correction` normalise la langue**, comme le type de document. La valeur source reste dans `raw_metadata.language`. Une valeur non reconnue, `und` compris, donne NULL.
- **Une facette « Langues »** dans les listes de publications.

## Phasage

### 1. Référentiel

- [x] Tables `languages` et `language_forms`, remplies par la migration depuis les données d'ISO 639 (pycountry), exportées par le seed commun (fa51da9c).

### 2. Normalisation

- [x] Fonction du domaine qui ramène une valeur de source à un code du référentiel (e61ee8d3).
- [x] Appel dans la passe unaire de `metadata_correction`, valeur source gardée dans `raw_metadata.language` (e61ee8d3).
- [x] Reprise de `publications.language` : la passe marque `keys_dirty` sur les `source_publications` dont la langue change, et la réconciliation recalcule la langue de leurs publications (e61ee8d3).

### 3. Facette

- [x] Filtre et facette « Langues » dans les listes de publications, avec les libellés du référentiel.
- [x] Nom de la langue dans le volet des publications de l'administration, avec en note la valeur que donnait la source.

## Questions ouvertes

- **theses.fr** : demander le détail de chaque thèse pour lire `langues`, au prix d'une requête par thèse ? Quelle langue retenir quand la liste en compte plusieurs ?
- **Letton d'OpenAlex** : les 821 `lv` sont-ils des erreurs de détection à écarter ? La question relève de la base de production.
