# Chantier — Identifiants des enregistrements sources

## Contexte

Les identifiants d'un enregistrement source sont dans la colonne `doi` et dans l'objet JSONB `external_ids` : `hal_id` en liste, `nnt`, `pmid`, `pmcid`, `arxiv_id`, `related_dois`, `isbn`, `eisbn`. Environ 35 modules lisent `external_ids`.

- La normalisation écrit `external_ids` sous des formes hétérogènes : liste ou valeur unique selon le type.
- La phase `metadata_correction` retire des identifiants de trois façons. La correction unaire garde la valeur d'origine dans `corrections` (clés de thèse, dépôts HAL introuvables). La correction par DOI partagé note les valeurs retirées sous `removed_external_ids`, que la correction unaire réapplique. Le DOI faux est mis à nul, sa valeur d'origine gardée dans `corrections`.
- La réconciliation a une branche SQL par type d'identifiant, avec un index d'expression par clé. Seul le premier `hal_id` est une clé de rapprochement.
- Un identifiant absent de son registre est inscrit dans `failed_lookups`, que chaque usage doit rejoindre.
- `fetch_missing`, les relations et la vue `candidate_dois` déplient `external_ids` chacun à sa manière.

### Inventaire

Valeurs en base au 2026-10-28. Le DOI principal est dans la colonne `doi` pour toutes les sources.

| Type | Source : origine (valeurs) | Rapprochement actuel |
|---|---|---|
| `hal_id` | HAL : `halId_s` (64 791) ; OpenAlex : URL et identifiant des localisations (73 211, dont 3 679 enregistrements sources à plusieurs valeurs) ; ScanR : `externalIds` de type `hal` (64 947, dont 2 281 enregistrements sources à plusieurs valeurs) | premier seulement |
| `nnt` | HAL : `nntId_s` (2 794) ; OpenAlex : URL theses.fr (2 247) ; ScanR : identifiant ScanR (4 029) ; theses.fr : identifiant (5 066) | oui |
| `pmid` | OpenAlex : URL PubMed (16 995) ; ScanR : `externalIds` de type `pmid` (10 469) ; HAL : `pubmedId_s` (0) | oui |
| `pmcid` | HAL : `linkExtUrl_s` (2 556) ; OpenAlex : URL PMC (7 433) | non |
| `arxiv_id` | HAL : `linkExtUrl_s` (3 603) ; OpenAlex : URL arXiv (7 299) | oui |
| `related_dois` | OpenAlex : DOI des localisations autres que le DOI principal (15 141, dont 4 295 arXiv et 2 366 Zenodo) ; ScanR : `externalIds` de type `doi` autres que le DOI principal (1 278) ; DataCite : `relatedIdentifiers` de version, de forme, de partie et de supplément (17 806) | non |
| `isbn` | HAL : `idno` du TEI (4 242) ; Crossref : ISBN imprimé ou sans support (2 942) ; WoS (2 145) ; DataCite : identifiants et `IsPartOf` (628) | non |
| `eisbn` | Crossref : ISBN électronique (2 639) ; WoS (2) | non |

Localisation principale d'un échantillon de 10 000 works OpenAlex :

- DOI égal au DOI du work : 59 % ;
- HAL, work sans DOI : 26 % ;
- HAL, arXiv ou autre dépôt, work avec un DOI pris dans une autre localisation : 8,4 % ;
- autre dépôt sans DOI, ou MAG : 5,4 %.

Les enregistrements sources à ISBN sont surtout des chapitres (4 922), des communications (2 397) et des livres (1 368). Deux enregistrements sources WoS ont un PMID absent de la normalisation WoS.

Cas 245311 et 102233 : deux dépôts HAL d'un même texte, datés de 2020 et 2021, sans DOI. OpenAlex et ScanR citent les deux dépôts, dans un ordre inverse. Chaque enregistrement source rejoint la publication de son premier dépôt, et les deux publications restent séparées.

Paires de publications reliées par un `hal_id` actif, sur la base locale au 2026-10-28 (1 516 paires) :

- `hal_id` primaire ou dérivé des deux côtés : 67. Même document, avec deux DOI distincts : DOI de revue et DOI arXiv ou DESY (`10.3204/pubdb…`).
- primaire ou dérivé d'un côté, secondaire de l'autre : 1 429. Surtout des versions distinctes : communication et article, poster et acte. Quelques doublons sans DOI.
- secondaire des deux côtés : 20.

Publications de la base locale scindées quand seuls les identifiants primaires et dérivés sont des clés : 1 289 par la règle sur le `hal_id`, 337 de plus par la même règle sur le PMID et l'identifiant arXiv. Parmi elles, des dépôts HAL sans DOI séparés de leur version éditeur, et des enregistrements sources ScanR `pmid…` séparés de leur article.

Réconciliation simulée sur la base locale au 2026-10-29 (341 073 enregistrements sources rattachables), face à la clé DOI de la colonne :

- DOI actifs `primary` ou `derived` comme seules clés DOI : 11 234 partitions scindées. Les DOI de HAL, WoS et theses.fr sont `secondary` : 7 865 enregistrements sources WoS, 2 974 dépôts HAL et 1 189 works OpenAlex quittent leur publication.
- Tous les DOI actifs de rôle autre que `related` comme clés, sans coupe par DOI : 6 632 fusions, jusqu'à 100 publications. Un work OpenAlex cite en DOI `secondary` les fichiers d'un jeu de données ou les versions d'un logiciel.
- Tous les DOI actifs de rôle autre que `related` comme clés, le DOI `secondary` cédant le premier : 144 publications perdent un enregistrement source et 210 fusionnent. Ce sont surtout des enregistrements sources ScanR dont l'identifiant ScanR désigne l'article et le premier DOI des `externalIds` le preprint : ils passent de la publication du preprint à celle de l'article.

Usages qui demandent un seul DOI par enregistrement source :

- coupe des partitions et ancre de la réconciliation ;
- DOI de la publication en consolidation ;
- groupes de la correction par DOI partagé ;
- DOI propre du déclarant DataCite (cibles, relations) ;
- rattachement d'une revue par espace de noms DOI, type d'éditeur du registrant.

Les autres usages acceptent plusieurs DOI : `fetch_missing`, `known_dois`, `resolve_ra`, apprentissage des référentiels, règles de correction sur le préfixe, `is_matchable`.

## Décisions

- Une table relie un enregistrement source à un identifiant : type, valeur, rôle, statut. Les identifiants d'une publication se déduisent de ses enregistrements sources.
- Rôle d'un identifiant dans un enregistrement source :
  - primaire : identifiant de l'enregistrement dans la source, soit le DOI chez Crossref et DataCite, le `hal_id` chez HAL, le NNT chez theses.fr ;
  - dérivé : identifiant de l'enregistrement d'une autre source dont l'enregistrement source est dérivé. Un enregistrement source a au plus un identifiant dérivé ;
  - secondaire : identifiant que la source attribue au même document ;
  - lié : identifiant d'un document lié, par exemple un DOI apparenté ou l'ISBN de l'ouvrage hôte.
- L'identifiant dérivé est un identifiant d'un type de la table :
  - chez ScanR, l'identifiant que contient l'identifiant ScanR (`doi…`, `hal…`, `nnt…`, `pmid…`) ;
  - chez OpenAlex, l'identifiant de la localisation principale (`primary_location`). Le DOI du work est secondaire quand il diffère de cet identifiant.
- Un ISBN est secondaire pour un livre et lié pour un autre document. DataCite distingue les ISBN du document de ceux de son conteneur.
- Les identifiants OpenAlex et WoS restent seulement dans `source_id`.
- Statut : actif, ou retiré par une règle de correction nommée. Chaque passage de `metadata_correction` recalcule les statuts à partir de tous les identifiants de la table. Chaque sous-étape réécrit seulement les statuts de ses règles. Un identifiant retiré par la règle d'une autre sous-étape reste retiré.
- `corrections` garde seulement les valeurs d'origine des colonnes.
- La correction par DOI partagé garde ou retire chaque DOI.
- Le DOI d'une version, d'une variante ou d'une pièce de dataset a une cible quand l'œuvre principale est présente en base : DOI concept, forme principale ou dataset parent. La table `doi_targets` relie les deux DOI.
- La cible tient lieu du DOI pour tous les enregistrements sources qui ont ce DOI, dans la réconciliation et la consolidation.
- L'enregistrement source DataCite de la forme secondaire est écarté de la réconciliation (`is_matchable`).
- Clés de la réconciliation : tous les DOI actifs de rôle autre que `related`, `hal_id`, NNT, PMID et identifiant arXiv. Pour les quatre derniers, la clé est l'identifiant actif de rôle le plus fort, puis de plus petite valeur.
- Coupe d'une composante de la réconciliation par DOI : ses ancres sont ses DOI `primary` et `derived` ; à défaut, les DOI des membres qui ont un seul DOI. Une composante à une ancre au plus reste entière. Sinon, un membre rejoint l'ancre de son DOI `primary` ou `derived`, à défaut l'unique ancre parmi ses DOI `secondary` ; un membre sans ancre unique reste sur sa publication.
- Un identifiant absent de son registre est invalide. L'invalidité se calcule par jointure sur `failed_lookups`.
- La colonne `doi` disparaît au profit de l'identifiant DOI de l'enregistrement source.

## Phasage

### Phase 1 — Table et normalisation

- [x] Inventaire des identifiants par source et par type, avec leur rôle.
- [x] Table des identifiants des enregistrements sources et migration (570949717).
- [x] Écriture de la table par la normalisation (05e2c6e63).
- [x] Remplissage du stock par un script oneshot : identifiants calculés depuis les payloads du raw store par la fonction de la normalisation (16df3eee9). En production, le script passe avant les migrations et le premier pipeline.

### Phase 2 — Corrections

- [x] Retraits de la correction unaire (clés de thèse, dépôts HAL introuvables) en statuts (8790b3c34).
- [x] Retraits de la correction par DOI partagé en statuts (8790b3c34).
- [x] `is_matchable` calculé depuis la table (8790b3c34).
- [x] Suppression des formats de retrait dans `corrections` (`external_ids`, `removed_external_ids`) (8790b3c34).

### Phase 3 — Rapprochement

- [x] Mesure des paires de publications reliées par un identifiant actif, selon son rôle.
- [x] Mesure des publications scindées quand seuls les identifiants primaires et dérivés sont des clés.
- [x] Voisinage de la réconciliation par une jointure sur le type et la valeur des identifiants actifs, avec les clés d'`external_ids` (34ab26da6).

### Phase 4 — Autres lectures

- [x] `fetch_missing` et `candidate_dois` (3f932bce4).
- [x] Relations entre publications (d985bbb41).
- [x] Modèles de lecture de l'API et affichage (1bb499b59).

### Phase 5 — Retrait de `external_ids`

- [x] Suppression de la colonne (77739fdaa).

### Phase 6 — Retrait de la colonne `doi`

- [x] Code mort des formes secondaires rattachées à une publication : priorité de la consolidation, groupement des contributions sources, copies et sources secondaires de l'API.
- [x] Table `doi_targets`, écrite par la correction par DOI partagé et lue par la réconciliation et la consolidation. Enregistrement source DataCite de la forme secondaire écarté.
- [x] Sous-étapes distinctes de `metadata_correction` : `doi_targets` écrit les cibles, `remove_identifiers` les retraits. DOI des formes secondaires rendus au stock par une migration.
- [x] Cible appliquée au DOI cible d'une relation entre publications (`doi_or_target_sql`).
- [x] Usages du DOI d'un enregistrement source, et réconciliation simulée selon la règle des clés DOI.
- [x] DOI des enregistrements sources sans payload au raw store écrits dans la table (oneshot, 086044c44).
- [x] Clés DOI et coupe de la réconciliation selon les ancres ; DOI de la publication pris sur l'ancre de ses enregistrements sources.
- [x] DOI des déclarants de `doi_targets` lus dans la table (a9d54c779).
- [x] Groupes de `remove_identifiers` par DOI de la table, de rôle autre que `related` : un enregistrement source appartient à un groupe par DOI et perd seulement le DOI du groupe qui le désigne. Sur la base locale, 40 retraits de plus (1 164 au lieu de 1 124), aucun en moins.
- [x] `is_matchable` sur la table : préfixe exclu quand tous les DOI propres de l'enregistrement source l'ont (`primary` ou `derived`, à défaut `secondary`) ; forme secondaire DataCite par son DOI `primary` ; agrégateur gardé par un DOI actif de rôle autre que `related`.
- [ ] Lectures du DOI dans la table : réconciliation, `metadata_correction`, `fetch_missing` et `known_dois`, `resolve_ra`, consolidation, statut open access, relations, modèles de lecture de l'API. Les lectures qui identifient l'œuvre passent par `doi_or_target_sql`, celles qui interrogent un service par DOI lisent le DOI tel quel.
- [ ] Suppression de la colonne.

### Phase 7 — DOI bioRxiv et medRxiv

- [ ] DOI bioRxiv et medRxiv (préfixe 10.1101) exposés par les sources, par exemple dans les localisations OpenAlex (publication 2757).

### Phase 8 — Documentation

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Règles de `remove_identifiers` à revoir. La sous-étape retire les DOI manifestement faux : inconnus de doi.org, ou attribués à tort, surtout le DOI d'un ouvrage donné à un chapitre et celui d'un volume d'actes donné à une communication. Un chapitre perd le DOI d'un ouvrage quel que soit son titre ; le type que Crossref donne au DOI suffit à le trancher. L'absence de nom d'auteur commun entre un dépôt HAL et l'enregistrement source Crossref est un indice trop approximatif : beaucoup d'ouvrages Crossref n'ont aucun auteur.
- DOI preprints.org (`10.20944/preprints…`) inscrits dans `failed_lookups` comme inconnus de doi.org, à vérifier.

- Hors périmètre : retrait des identifiants secondaires trop éloignés de l'enregistrement source qui les cite, par comparaison deux à deux des titres par exemple. Ce serait une généralisation de `remove_identifiers` à tous les identifiants.
