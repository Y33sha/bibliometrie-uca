# Chantier — Identifiants des enregistrements sources

## Contexte

Les identifiants d'un enregistrement source sont dans la colonne `doi` et dans l'objet JSONB `external_ids` : `hal_id` en liste, `nnt`, `pmid`, `pmcid`, `arxiv_id`, `related_dois`, `isbn`, `eisbn`. Environ 35 modules lisent `external_ids`.

- La normalisation écrit `external_ids` sous des formes hétérogènes : liste ou valeur unique selon le type.
- La phase `metadata_correction` retire des identifiants de trois façons. La correction unaire garde la valeur d'origine dans `corrections` (clés de thèse, dépôts HAL introuvables). La correction par DOI partagé note les valeurs retirées sous `removed_external_ids`, que la correction unaire réapplique. Le DOI faux est mis à nul, sa valeur d'origine gardée dans `corrections`.
- La réconciliation a une branche SQL par type d'identifiant, avec un index d'expression par clé. Seul le premier `hal_id` est une clé de rapprochement.
- Un identifiant absent de son registre est inscrit dans `failed_lookups`, que chaque usage doit rejoindre.
- `fetch_missing`, les relations et la vue `candidate_dois` déplient `external_ids` chacun à sa manière.

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

- [ ] Inventaire des identifiants par source et par type, avec leur rôle.
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
