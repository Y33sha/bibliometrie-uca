# Simplification de la phase sujets

## Contexte

La phase `subjects` moissonne dans `subjects` / `publication_subjects` **deux natures** de sujets : les mots-clés libres (champ `keywords` des `source_publications`, termes auteur non contrôlés) et les concepts issus d'ontologies (champ `topics` : domaines HAL, topics OpenAlex, subjects/headings WoS, discipline/RAMEAU theses, domaines ScanR). Autour de ça, un appareillage lourd qu'une relecture montre largement inexploité :

- **Mots-clés libres** : globalement du bruit, plus une gêne qu'un signal en l'état.
- **Hiérarchie `level` / `parent`** (chaînage 4 niveaux d'OpenAlex, suivi dans le cache) : lue par **aucune** feature produit. Aucune requête API ne renvoie `level`/`parent`, le front ne navigue aucune arborescence. Seul consommateur : le CLI de maintenance `cleanup_oa_subjects`.
- **`codes`** (annotation `{ontologie: {codes:[…]}}`) : un seul consommateur, un tooltip sur la page détail d'un sujet. Réel uniquement pour HAL (vrais codes CCSD, distincts du libellé, parfois multiples) ; pour les 5 autres sources `codes = [lower(label)]`, pure redondance avec le libellé — le « intitulé tient lieu d'id ».
- **`score`** (pertinence OpenAlex du topic feuille) : écrit dans `publication_subjects.score`, relu par aucune feature (ni API, ni front, ni co-occurrences) et peu fiable (scores élevés observés sur des sujets manifestement erronés).
- Le `SubjectCache` porte une machinerie `_covers` / merge `ON CONFLICT` uniquement pour peupler ces champs inexploités.

Sur la fiche publication, les mots-clés libres sont affichés **via `publication_subjects`** (le `SubjectsBlock` sépare `concepts` et `freeKeywords` sur `ontologies == {}`), pas via un champ dédié — les en retirer suppose de re-sourcer leur affichage.

## Décisions

1. **Les mots-clés libres quittent la phase sujets.** Ils restent portés par `source_publications` et continuent d'être affichés sur la fiche publication, re-sourcés depuis `publications_detail.keywords` (agrégat des sources, indépendant de `publication_subjects`). Ils ne peuplent plus `subjects` ni `publication_subjects` et disparaissent de la page `/subjects`. Réévalués plus tard, dans le chantier qualité des sujets, comme source possible de rattachement à des sujets normalisés — hors de cette fiche.
2. **Plus de hiérarchie.** `level` et `parent` supprimés. Les 4 niveaux OpenAlex restent, **à plat** : 4 concepts liés à la publication, sans relation parent/enfant. Une vraie hiérarchie, si elle sert un jour, viendra de vrais identifiants de topics OpenAlex moissonnés, pas du label-tenant-lieu-d'id actuel.
3. **Plus de score.** La colonne `publication_subjects.score` est supprimée (non lue, peu fiable). Les scores OpenAlex ne sont plus repris.
4. **Plus de `codes`.** Les codes CCSD HAL, s'ils redeviennent utiles, se remoissonnent.
5. **`cleanup_oa_subjects` est supprimé** : sans `level`/`parent`, il n'a plus de matière.
6. **La colonne `subjects.ontologies` disparaît entièrement.** Vidée de `codes`/`level`/`parent`, elle ne portait plus que l'appartenance à une ontologie, sans usage : la granularité `wos_subject` vs `wos_heading` n'est exploitée nulle part. Les badges d'ontologie disparaissent donc des pages sujets ; la provenance reste disponible sur `publication_subjects.source`. Les constantes `ONTOLOGY_*` (y compris `ONTOLOGY_OPENALEX_KEYWORD`, jamais produite) sont retirées. Un sujet se réduit à `label` + `language` + `usage_count`.

## Phasage

### Phase A — Sortir les mots-clés libres

- [x] Ingestors : n'ingérer que `topics` (concepts). Le champ `keywords` n'alimente plus `subjects` / `publication_subjects` ; l'ingestor CrossRef (libres seuls) est supprimé. (`6b85ac57`)
- [x] Fiche publication : afficher les mots-clés libres depuis `publications_detail.keywords` (champ `keywords` de la réponse détail + `SubjectsBlock`), indépendamment de `publication_subjects`. (`b7db61df`)
- Le stock existant de sujets/liens libres se nettoie côté données prod (le code cesse d'en produire ; `purge_orphan_subjects` retire les sujets devenus sans lien après re-ingestion). Pas de one-shot ici.

### Phase B — Supprimer le modèle d'ontologie

- [x] Migration : `DROP COLUMN publication_subjects.score` **et** `DROP COLUMN subjects.ontologies` (+ index partiel `idx_subjects_oa_label_lower`). (`5031bb61`)
- [x] Retirer `ontologies` / `OntologyEntry` de `upsert_subject` (SQL + port pipeline), de `SubjectCache`, des ingestors ; `upsert_subject` ne prend plus que `label` + `language`. (`6b85ac57`)
- [x] Retirer `SubjectOntologyEntry` (port API) et le champ `ontologies` des DTO sujets et des `SELECT`. (`b7db61df`)
- [x] `domain/subjects/subject.py` : retirer les constantes `ONTOLOGY_*` (dont `ONTOLOGY_OPENALEX_KEYWORD`), ne garder que `normalize_label` ; docstring recalé. (`6b85ac57`)
- [x] Front : retirer les badges d'ontologie (pages `/subjects`, détail sujet, `SubjectsBlock`). Un sujet s'affiche par son libellé seul. (`b7db61df`)
- [x] Supprimer `cleanup_oa_subjects`. (`6b85ac57`)

### Phase C — Simplifier et factoriser le reste

- [x] `SubjectCache` réduit à `label → subject_id` (plus de suivi ontologies, plus de `_covers`). (`6b85ac57`)
- [x] Docstrings des ingestors recalés (format source décrit en clair, sans numéros de ligne ni renvoi chantier ni note de roadmap). `ingest_hal` garde la dérivation code CCSD → libellé (`hal_domain_label`), sans stocker le code. (`6b85ac57`)
- [x] Cinq modules `ingest_<source>` réduits à cinq extracteurs purs `topics → list[str]` (`extractors.py`) + registre `SUBJECT_EXTRACTORS` ; l'upsert/liaison n'est plus écrit qu'une fois, dans l'orchestrateur. (`12009caa`)

## Questions ouvertes

Aucune.
