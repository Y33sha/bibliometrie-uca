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
- Une version, une variante ou une pièce de dataset est écartée de la réconciliation (`is_matchable`) quand son DOI cible est présent en base : DOI concept, forme principale ou dataset parent. Son DOI est retiré de tous les enregistrements sources qui le citent.
- Deux DOI distincts empêchent la fusion, quel que soit le rôle des identifiants.
- Clés de la réconciliation : DOI, `hal_id`, NNT, PMID et identifiant arXiv. Pour les quatre derniers, la clé est l'identifiant actif de rôle le plus fort, puis de plus petite valeur.
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

- [x] Versions, variantes et pièces de dataset écartées quand leur DOI cible est en base.
- [ ] Code mort des formes secondaires rattachées à une publication : priorité de la consolidation, groupement des contributions sources, copies et sources secondaires de l'API.
- [ ] DOI d'une version, d'une variante ou d'une pièce de dataset retiré des enregistrements sources qui le citent.
- [ ] DOI d'un enregistrement source à plusieurs DOI actifs.
- [ ] Lectures du DOI dans la table : réconciliation, `metadata_correction`, `fetch_missing` et `known_dois`, `resolve_ra`, consolidation, statut open access, relations, modèles de lecture de l'API.
- [ ] Suppression de la colonne.

### Phase 7 — DOI bioRxiv et medRxiv

- [ ] DOI bioRxiv et medRxiv (préfixe 10.1101) exposés par les sources, par exemple dans les localisations OpenAlex (publication 2757).

### Phase 8 — Documentation

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- DOI d'un enregistrement source à plusieurs DOI actifs. La colonne `doi` contient le DOI que la source donne au document (`doi` du work OpenAlex, `doiId_s` HAL). Les autres DOI d'un work OpenAlex sont secondaires, comme celui-ci. Sur 10 000 works OpenAlex, 777 ont plusieurs DOI actifs : 423 un DOI Crossref et des DOI DataCite (arXiv, Zenodo, DESY), 242 seulement des DOI DataCite, 112 plusieurs DOI Crossref (bioRxiv, SSRN, Research Square).
