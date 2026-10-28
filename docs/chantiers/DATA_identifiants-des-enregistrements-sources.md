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

| Type | Source : origine (valeurs) | Clé de rapprochement | Rôle |
|---|---|---|---|
| `hal_id` | HAL : `halId_s` (64 791) ; OpenAlex : URL et identifiant des localisations (73 211, dont 3 679 enregistrements sources à plusieurs valeurs) ; ScanR : `externalIds` de type `hal` (64 947, dont 2 281 enregistrements sources à plusieurs valeurs) | premier seulement | premier : document ; suivants : secondaire |
| `nnt` | HAL : `nntId_s` (2 794) ; OpenAlex : URL theses.fr (2 247) ; ScanR : identifiant ScanR (4 029) ; theses.fr : identifiant (5 066) | oui | document |
| `pmid` | OpenAlex : URL PubMed (16 995) ; ScanR : `externalIds` de type `pmid` (10 469) ; HAL : `pubmedId_s` (0) | oui | document |
| `pmcid` | HAL : `linkExtUrl_s` (2 556) ; OpenAlex : URL PMC (7 433) | non | document |
| `arxiv_id` | HAL : `linkExtUrl_s` (3 603) ; OpenAlex : URL arXiv (7 299) | oui | document |
| `related_dois` | OpenAlex : DOI des localisations autres que le DOI principal (15 141, dont 4 295 arXiv et 2 366 Zenodo) ; ScanR : `externalIds` de type `doi` autres que le DOI principal (1 278) ; DataCite : `relatedIdentifiers` de version, de forme, de partie et de supplément (17 806) | non | œuvre apparentée |
| `isbn` | HAL : `idno` du TEI (4 242) ; Crossref : ISBN imprimé ou sans support (2 942) ; WoS (2 145) ; DataCite : identifiants et `IsPartOf` (628) | non | selon le type de document |
| `eisbn` | Crossref : ISBN électronique (2 639) ; WoS (2) | non | selon le type de document |

Les enregistrements sources à ISBN sont surtout des chapitres (4 922), des communications (2 397) et des livres (1 368). Deux enregistrements sources WoS ont un PMID absent de la normalisation WoS.

Cas 245311 et 102233 : deux dépôts HAL d'un même texte, datés de 2020 et 2021, sans DOI. OpenAlex et ScanR citent les deux dépôts, dans un ordre inverse. Chaque enregistrement source rejoint la publication de son premier dépôt, et les deux publications restent séparées.

## Décisions

- Une table relie un enregistrement source à un identifiant : type, valeur, rôle, statut. Les identifiants d'une publication se déduisent de ses enregistrements sources.
- Rôle d'un identifiant :
  - identifiant du document, clé de rapprochement ;
  - identifiant secondaire du document, hors rapprochement : identifiants HAL après le premier chez OpenAlex et ScanR. Ces agrégateurs réunissent parfois des dépôts HAL de publications distinctes ;
  - identifiant d'une œuvre apparentée : DOI apparenté, ISBN de l'ouvrage hôte.
- Statut : actif, ou retiré par une règle de correction nommée. Chaque passage de `metadata_correction` recalcule les statuts.
- Un identifiant absent de son registre est invalide. L'invalidité se calcule par jointure sur `failed_lookups`.
- La colonne `doi` reste en place.

## Phasage

### Phase 1 — Table et normalisation

- [x] Inventaire des identifiants par source et par type, avec leur rôle.
- [ ] Table des identifiants des enregistrements sources, migration et remplissage depuis `external_ids`.
- [ ] Écriture de la table par la normalisation.

### Phase 2 — Corrections

- [ ] Retraits de la correction unaire (clés de thèse, dépôts HAL introuvables) en statuts.
- [ ] Retraits de la correction par DOI partagé en statuts.
- [ ] `is_matchable` calculé depuis la table.

### Phase 3 — Rapprochement

- [ ] Voisinage de la réconciliation par une jointure sur le type et la valeur des identifiants actifs du document.
- [ ] Mesure des paires de publications reliées par un identifiant HAL secondaire.

### Phase 4 — Autres lectures

- [ ] `fetch_missing` et `candidate_dois`.
- [ ] Relations entre publications.
- [ ] Modèles de lecture de l'API et affichage.

### Phase 5 — Retrait de `external_ids`

- [ ] Suppression de la colonne et des formats de retrait dans `corrections`.

### Phase 6 — DOI bioRxiv et medRxiv

- [ ] DOI bioRxiv et medRxiv (préfixe 10.1101) exposés par les sources, par exemple dans les localisations OpenAlex (publication 2757).

### Phase 7 — Documentation

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Colonne `doi` : gardée à côté de la table, ou remplacée par l'identifiant DOI du document.
- Identifiants HAL secondaires : réintégration au rapprochement sous condition, au vu de la mesure de la phase 3.
- Rôle de l'ISBN : identifiant du document pour un ouvrage, identifiant d'une œuvre apparentée pour un chapitre.
