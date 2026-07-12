# Simplification de la phase sujets

## Contexte

La phase `subjects` moissonne dans `subjects` / `publication_subjects` **deux natures** de sujets : les mots-clés libres (champ `keywords` des `source_publications`, termes auteur non contrôlés) et les concepts issus d'ontologies (champ `topics` : domaines HAL, topics OpenAlex, subjects/headings WoS, discipline/RAMEAU theses, domaines ScanR). Autour de ça, un appareillage lourd qu'une relecture montre largement inexploité :

- **Mots-clés libres** : globalement du bruit (termes très génériques ou idiosyncratiques), plus une gêne qu'un signal en l'état.
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

- [ ] Ingestors : n'ingérer que `topics` (concepts). Le champ `keywords` n'alimente plus `subjects` / `publication_subjects`.
- [ ] Fiche publication : afficher les mots-clés libres depuis `publications_detail.keywords` (ajout côté API `publications/detail` + front), indépendamment de `publication_subjects`. Le `SubjectsBlock` ne montre plus que des concepts.
- [ ] Le stock existant de sujets/liens libres se nettoie côté données prod (le code cesse d'en produire ; `purge_orphan_subjects` retire les sujets devenus sans lien après re-ingestion). Pas de one-shot ici.

### Phase B — Supprimer le modèle d'ontologie

- [ ] Migration : `DROP COLUMN publication_subjects.score` **et** `DROP COLUMN subjects.ontologies`.
- [ ] Retirer `ontologies` / `OntologyEntry` de `upsert_subject` (SQL + port pipeline), de `SubjectCache`, des ingestors ; `upsert_subject` ne prend plus que `label` + `language`.
- [ ] Retirer `SubjectOntologyEntry` (port API) et le champ `ontologies` des DTO sujets (`SubjectOut`, `SubjectListItem`, `SubjectNeighborOut`, `SubjectFrequency`) ; retirer `ontologies` des `SELECT`.
- [ ] `domain/subjects/subject.py` : retirer les constantes `ONTOLOGY_*` (dont `ONTOLOGY_OPENALEX_KEYWORD`), ne garder que `normalize_label` ; docstring recalé.
- [ ] Front : retirer les badges d'ontologie (pages `/subjects`, détail sujet, `SubjectsBlock`, nuages). Un sujet s'affiche par son libellé seul.
- [ ] Supprimer `cleanup_oa_subjects`.

### Phase C — Simplifier et factoriser le reste

- [ ] `SubjectCache` réduit à `label → subject_id` (plus de suivi ontologies, plus de `_covers`).
- [ ] Ingestors uniformisés autour d'un helper commun de ramassage de libellés (le bloc de liaison est aujourd'hui dupliqué à l'identique dans les six modules). `ingest_hal` garde la dérivation code CCSD → libellé (`hal_domain_label`), mais ne stocke plus le code.
- [ ] Docstrings des ingestors : citer les fonctions productrices de la forme source (au lieu des numéros de ligne, qui pourrissent), retirer les renvois à des fiches chantier et les notes de roadmap (« Phase ultérieure »).

## Questions ouvertes

Aucune.
