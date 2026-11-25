# Chantier — Refactorisation : normalisation

## Contexte

Suite de la relecture du pipeline dans l'ordre d'exécution, selon *A Philosophy of Software Design* (John Ousterhout). La [fiche précédente](archived/2026-11-17_CODE_refacto-fin-du-moissonnage.md) couvre la fin du moissonnage.

## Décisions

- Périmètre de la fiche : phase `normalize` (`pipeline/ingestion/common/normalize.py`) et patron `SourceNormalizer` (`pipeline/ingestion/common/normalizer.py`). Les normaliseurs de chaque source respectent le patron et restent hors périmètre.

## Phasage

### Phase 1 — Journal

- [x] Le récapitulatif des documents écartés s'écrit pendant la normalisation, avant la ligne de bilan de sa source, écrite par l'exécuteur au retour de la tâche. Il s'affiche donc sous la source précédente : les 22 documents écartés de Crossref suivent « OPS : rien à faire ». Les identifiants remontent dans les métriques de la tâche, et l'exécuteur les écrit sous la ligne de bilan.
- [x] L'avertissement « Type de document inconnu » (`source_records._doc_type`) s'écrit une fois par document, hors de l'arbre, à chaque normalisation du même document. Les types inconnus se comptent par type et rejoignent le récapitulatif de la source : « 6 documents de type inconnu `study-registration` ».
- [x] Une exception sur un document s'écrit sans sa pile d'appels (`slog.error(f"Erreur sur …")`). Passage à `logger.exception`.
- [x] `_withhold_authors` et `_prune` dessinent eux-mêmes leur branche (`BRANCH`, `LAST_BRANCH`), et `_prune` se sait dernière ligne de la section. Les deux tâches passent par `metrics.report`, comme les suppressions de lignes orphelines.

### Phase 2 — Documents écartés et erreurs

- [ ] Un document écarté faute de métadonnées compte comme une erreur : « Crossref : 115 documents normalisés, 22 erreurs » désigne 22 suppléments (`.supp1`, `.g001`), écartés à raison. `process_work` renvoie un booléen à trois états (`True`, `False`, `None`). Une énumération de l'issue d'une ligne le remplace : normalisée, écartée, vide. `NormalizeStats` gagne un compteur des documents écartés, distinct des erreurs.
- [ ] Le commit périodique se déclenche sur `processed + skipped`, sans les documents écartés. Le déclencheur devient la taille de `done_ids`. `DEFAULT_BATCH_SIZE`, redéfini par chaque source, devient `BATCH_SIZE`.

### Phase 3 — Patron `SourceNormalizer`

- [ ] `run` commence par `self.conn.rollback()`, sur une transaction ouverte par l'appelant juste avant. Suppression.
- [ ] Le crochet `cleanup` vide un cache juste avant l'abandon du normaliseur, construit pour un seul `run`. Seul OpenAlex le définit. Suppression du crochet.

### Phase 4 — Docstrings

- [ ] Docstring du module `normalize` : la phrase sur le TEI de HAL rejoint `pipeline/ingestion/hal/normalize.py`. La liste des tâches redit la déclaration de la phase, et la phrase sur le `VACUUM` redit `maintenance=`. Suppression des deux.
- [ ] Les docstrings perdent leur connaissance de la CLI et de l'exécuteur : `--normalize-full` dans `_normalize`, « la ligne affiche « rien à faire » » dans `_report`, « ferme la section de normalisation » dans `_prune`. Celle de `_reject` dit « compté comme document incomplet », et le code le compte comme erreur : à aligner sur la phase 2.
- [ ] La phrase de l'étape `removals` nomme les documents disparus avant les enregistrements sources INSPIRE-HEP, dans l'ordre inverse des tâches.

## Questions ouvertes

- Les compteurs de la phase 2 vont dans `pipeline_phase_executions` : une clé des documents écartés s'ajoute à la table de la phase, avec sa colonne dans l'administration. La clé `disappeared_pruned` de `assemble` n'a aucun lecteur. Changement des données stockées, à décider.
- `--normalize-full` vide l'empreinte du bloc auteurs. Un enregistrement source déjà normalisé repasse par `normalize` seulement si son payload revient dans `staging`, par `rehydrate_staging_from_raw_store` ou un changement chez la source. Seule, l'option ne produit rien de visible. La rattacher à la commande de réinjection supprimerait une option de `run_pipeline` et le piège.
