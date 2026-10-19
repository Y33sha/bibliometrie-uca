# Chantier — Reconstruction après un changement de règle

## Contexte

Le pipeline recalcule seulement ce qui a changé. Une règle modifiée s'applique au stock par une option de `run_pipeline` :

- `--rebuild-publications` marque toutes les notices `keys_dirty`, puis la réconciliation suit son chemin ordinaire ;
- `--rebuild-subjects` remplace la sélection des publications à ingérer par toutes les publications ;
- `--normalize-full` synchronise les signatures d'une notice même si l'empreinte de son bloc auteurs est inchangée ;
- `--rebuild-authorships` vide la table `authorships` avant sa construction.

La construction ordinaire de `authorships` traite toute la table : insertion des paires manquantes, suppression des orphelines, recomposition des attributs. `--rebuild-authorships` aboutit au même contenu, sous d'autres identifiants.

L'opérateur doit savoir qu'une règle a changé, et quelle option la propage. Sans l'option, la règle s'applique seulement aux données recalculées ensuite.

## Décisions

- Une reconstruction marque à recalculer, puis suit le chemin ordinaire, comme `--rebuild-publications`.
- `--rebuild-authorships` est retirée.

## Phasage

### Phase 1 — Un seul mécanisme

- [ ] `--rebuild-subjects` marque toutes les publications à ingérer.
- [ ] `--normalize-full` marque toutes les notices à resynchroniser.
- [ ] Retrait de `--rebuild-authorships` et de `purge_authorships`.

### Phase 2 — Version des règles

- [ ] Inventaire des règles dont le changement demande une reconstruction : clés de réconciliation, normalisation des auteurs, ingestion des sujets.
- [ ] Mécanisme retenu, selon la question ouverte.

### Phase 3 — Documentation

- [ ] Mise à jour de `docs/pipeline` et de `docs/exploitation`.

## Questions ouvertes

- Une version de chaque règle, stockée avec les données qu'elle produit, marquerait à recalculer les lignes d'une version antérieure, et rendrait les options inutiles. Changement de schéma : stockage par ligne, ou par table dans la configuration.
