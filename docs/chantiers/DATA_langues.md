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

**Le référentiel des pays sert de modèle** : table `countries (code, name)`, facette « Pays » des listes de publications.

## Décisions

- **Une table `languages (code, name)`** sert de référentiel. Le code est celui d'ISO 639-1 quand il existe, celui d'ISO 639-3 sinon, comme dans BCP 47. Les libellés sont en français, pour l'affichage.
- **Une facette « Langues »** dans les listes de publications.

## Phasage

### 1. Référentiel

- [ ] Table `languages`, migration et seed.

### 2. Normalisation

- [ ] Fonction du domaine qui ramène une valeur de source à un code du référentiel : codes à deux lettres, codes à trois lettres, noms anglais.
- [ ] Application de cette fonction aux `source_publications`, selon la question ouverte ; clé étrangère de `publications.language` vers `languages`.
- [ ] Reprise du stock.

### 3. Facette

- [ ] Filtre et facette « Langues » dans les listes de publications, avec les libellés du référentiel.

## Questions ouvertes

- **Où normaliser** : dans la passe unaire de `metadata_correction`, comme le type de document ? La valeur source reste alors dans `raw_metadata.language`, une valeur non reconnue ou `und` donne NULL, et la reprise du stock se réduit à un passage de la phase.
- **theses.fr** : demander le détail de chaque thèse pour lire `langues`, au prix d'une requête par thèse ? Quelle langue retenir quand la liste en compte plusieurs ?
- **Letton d'OpenAlex** : les 821 `lv` sont-ils des erreurs de détection à écarter ? La question relève de la base de production.
