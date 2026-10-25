# Pertinence des sujets

## Contexte

Base locale au 2026-10-25 : 74 585 publications, 734 400 liens publication–sujet, dont 566 967 (77 %) viennent d'OpenAlex.

- **Sujets OpenAlex aberrants.** Ils sont fréquents à l'inspection, surtout sur les revues généralistes et pluridisciplinaires. Le `score` OpenAlex est stocké dans `source_records.topics`. L'ingestion des sujets l'ignore.
- **Rejet inutilisé.** La colonne `publication_subjects.rejected` existe, mais aucun code ne l'écrit. L'ingestion conserve les liens rejetés. `usage_count` et `subject_cooccurrences` les écartent, donc les pages `/subjects` et `/subjects/[id]` aussi. Les nuages de sujets (`entity_subjects_sql`), le filtre par sujet et la fiche d'une publication les montrent.
- **Publications sans sujet** : 1 626.
- **Sujet incohérent avec la revue** : signal inexploité. Les sujets DOAJ sont connus pour 2 325 revues sur 10 860 (`serials.doaj_payload`).
- **Libellés à la place des codes.** Chaque enregistrement source porte le libellé de ses sujets, et l'extracteur lie les publications aux libellés. Les codes existent pourtant : HAL les porte dans chaque entrée de domaine (`sdv.bbm.bm_FacetSep_…`), ScanR stocke le PPN des vedettes sudoc. Le normalizer OpenAlex (`extract_topics`) garde le nom et le score de chaque niveau, et écarte les identifiants.
- **Hiérarchie aplatie.** `subjects` porte un libellé, sans vocabulaire ni parent. Deux vocabulaires qui partagent un libellé partagent un sujet. La chaîne domain → field → subfield → topic d'OpenAlex existe seulement dans `source_records.topics`.
- **Discipline des thèses en double.** La fiche d'une thèse lit `source_extras.discipline`. L'extracteur de sujets lit la copie `topics.discipline`.

### Constats de l'exploration (corpus de 46 000 publications)

**Score OpenAlex des topics feuille.** Distribution bimodale : 52 000 liens à 0,9 ou plus (65 %), 16 000 sous 0,1. Qualification à l'œil :

| Score | Aberrations | Vrais positifs |
|---|---|---|
| ≥ 0,9 | 15 à 20 % | 80 à 85 % |
| < 0,1 | 25 % | 50 à 60 %, topics secondaires pertinents |

Le score n'est pas une mesure de pertinence. Un seuil bas écarte des topics légitimes. Un seuil haut laisse le bruit.

**Paires de domains OpenAlex.** Health × Life est sur-représentée (lift 1,34), les cinq autres paires sous-représentées (0,27 à 0,62). Sur 15 publications Health × Physical (1 070 au total), 10 portent un domain manifestement aberrant. Les libellés HAL, WoS et theses.fr des autres enregistrements sources suffisent à trancher.

**Co-occurrences de sujets.** Les aberrations OpenAlex sont récurrentes : un même sujet mal attribué produit la même paire sur de nombreuses publications. Les paires rares ne les repèrent donc pas.

### Classifieurs ISTEX

La plateforme ISTEX TDM propose des web services de classification gratuits, appelables document par document. Aucun ne rend de score.

| Service | Entrée | Sortie | Performance annoncée |
|---|---|---|---|
| [halClass](https://services.istex.fr/classification-dans-les-domaines-hal/) | titre + résumé, français ou anglais | 1 domaine HAL parmi 13 : code, libellés fr et en | exactitude 0,87 |
| [openAlexClass](https://services.istex.fr/classification-en-domaines-scientifiques-openalex/) | résumé anglais | domain + field OpenAlex, libellés | F-mesure 0,88 sur domain |
| [sciencemetrixClass](https://services.istex.fr/classification-en-domaines-scientifiques-science-metrix/) | résumé anglais, 100 caractères minimum | 3 niveaux Science-Metrix, libellés | exactitude 0,85 |
| [pascalFrancisClass](https://services.istex.fr/classification-en-domaines-scientifiques/) | texte anglais | plan Pascal ou Francis, profondeur 1 à 3 | — |

## Décisions

- **Un sujet codé est identifié par son vocabulaire et son code.** La table des sujets porte son libellé et son parent. Les sources sans code gardent le libellé comme identifiant.
- **Vote des arbitres au grain des domains OpenAlex** (4 valeurs) :
  - arbitres : domaines HAL, catégories WoS, disciplines theses.fr de la même publication, sujets DOAJ de sa revue (premier niveau de la classification LCC) ;
  - un arbitre peut soutenir plusieurs domains (« Neurosciences » soutient Health et Life) ;
  - sur une publication à plusieurs domains, un domain sans soutien est rejeté si un autre domain a au moins un soutien. Le seuil « au moins deux soutiens » perd 12 vrais positifs sur 20 cas : les arbitres HAL réduits à « Sciences du Vivant » ne le franchissent jamais ;
  - le rejet d'un domain s'étend aux field, subfield et topics qui en descendent sur la publication ;
  - précision mesurée sur 15 publications : 10 vrais positifs, 1 faux positif, 4 cas limites.
- **Le vote est une règle du pipeline.** La phase `subjects` l'applique à chaque publication qu'elle ingère. Un rejet automatique se recalcule. Un rejet manuel est une décision humaine durable.
- **Classifieurs ISTEX avant Specter2.** Ils donnent un arbitre indépendant de l'algorithme OpenAlex, et des sujets aux publications qui n'en ont aucun. Specter2 se prototype seulement si leur évaluation montre qu'ils ne suffisent pas.
- **Specter2 au grain des topics feuille.** Embedding du titre et du résumé, centroïde par topic calculé sur les liens non rejetés, similarité cosinus, seuil calibré sur des cas qualifiés à l'œil.
- **Affichage des rejets.** Les liens rejetés sont exclus des décomptes et des listes : `/subjects`, `/subjects/[id]`, nuages de sujets des personnes, structures, revues et éditeurs, filtre par sujet. La fiche `/publications/[id]` les affiche barrés et grisés, pour le contrôle visuel des rejets.
- **Pistes écartées** : seuil sur le score OpenAlex, co-occurrences rares entre topics feuille, seuil « au moins deux soutiens ».

## Phasage

### Phase 1 — Sujets codés

- [ ] Schéma : vocabulaire, code, libellé et code parent des sujets ; contrainte d'unicité sur (vocabulaire, code)
- [ ] OpenAlex : `extract_topics` conserve l'identifiant de chaque niveau (`domains/2`, `fields/33`, `subfields/3312`, `T12443`) avec son nom et le score
- [ ] HAL : l'extracteur lit le code de domaine dans chaque entrée de `hal_domains` ; parent déduit du code (`sdv.bbm.bm` → `sdv.bbm`)
- [ ] ScanR : l'extracteur lit le PPN des vedettes sudoc
- [ ] theses.fr : l'extracteur lit la discipline dans `source_extras` ; le normalizer cesse d'écrire `topics.discipline`
- [ ] WoS et vedettes RAMEAU de theses.fr : identifiant selon la question ouverte « Sources sans code »
- [ ] Extracteurs de `subject_extractors.py` : ils rendent (vocabulaire, code, libellé, parent) ; `subject_cache` et `subject_store` écrivent par code
- [ ] Documentation : `docs/agregats/subjects.md`, `docs/donnees/03-publications.md`
- [ ] Stock : renormalisation depuis `staging` des enregistrements OpenAlex et theses.fr, puis `--rebuild-subjects`

### Phase 2 — Vote des arbitres

- [ ] Correspondance arbitres → domains OpenAlex, en données du domaine : codes de domaine HAL, catégories WoS, disciplines theses.fr, premier niveau LCC des sujets DOAJ
- [ ] Règle pure dans `domain/` : domains rejetés d'une publication et leurs descendants
- [ ] Ingestion de `subjects` : lecture des sujets DOAJ de la revue, application de la règle, marquage des liens rejetés automatiquement
- [ ] Une revue dont les sujets DOAJ changent remet ses publications dans l'ingestion des sujets ; lectures déclarées dans `pipeline/graph.py`
- [ ] Tests sur des publications réelles qualifiées à l'œil : paire Health × Physical, arbitre HAL réduit à « Sciences du Vivant », multi-affectation
- [ ] Mesure sur le stock : nombre de domains rejetés par paire, échantillon qualifié à l'œil pour vérifier la précision
- [ ] Documentation : `docs/agregats/subjects.md`

### Phase 3 — Rejets dans l'interface

- [ ] Nuages de sujets (`entity_subjects_sql`), filtre et facette par sujet (`infrastructure/read_models/filters.py`, `entity_facet.py`) : liens rejetés écartés
- [ ] `/publications/[id]` : `get_publication_subjects` rend le statut de rejet ; `SubjectsBlock.svelte` barre et grise les sujets rejetés
- [ ] Guide utilisateur : sens d'un sujet barré

### Phase 4 — Évaluation des classifieurs ISTEX

- [ ] Couverture : part des publications pourvues d'un résumé, d'un résumé anglais ; même mesure sur les publications sans sujet
- [ ] Échantillon de publications dont les sujets HAL, WoS ou theses.fr sont connus ; appels à halClass et openAlexClass
- [ ] Accord avec les sujets des sources et avec les domains OpenAlex retenus par le vote
- [ ] Décision d'usage : arbitre du vote, source de sujets pour les publications sans sujet, ou abandon

### Phase 5 — Specter2, si les classifieurs ISTEX ne suffisent pas

- [ ] Choix du modèle, de l'exécution et de la persistance des vecteurs (question ouverte « Specter2 »)
- [ ] Embeddings du titre et du résumé de chaque publication
- [ ] Centroïde par topic feuille OpenAlex, sur les liens non rejetés
- [ ] Similarité cosinus de chaque lien ; vue d'administration pour calibrer le seuil
- [ ] Rejet des liens sous le seuil

## Questions ouvertes

- **Stockage des rejets.** Le booléen `rejected` confond rejet automatique et rejet manuel. Un rejet manuel accroché à `publication_id` disparaît avec la publication. Quelle forme donner aux deux ?
- **Édition manuelle des rejets** : dans ce chantier ou dans [la gestion des publications dans l'administration](METIER_gestion-admin-des-publications.md) ?
- **Sources sans code.** WoS et theses.fr (discipline, vedettes RAMEAU) donnent-elles un code ? À défaut, le libellé sert d'identifiant.
- **Libellés et parents** : lus dans les enregistrements sources (chemin HAL, chaîne OpenAlex), ou dans les référentiels des sources (API HAL `ref/domain`, entités OpenAlex) ?
- **Provenance des sujets ISTEX** : l'énumération `source_type` de `publication_subjects.source` ne la prévoit pas.
- **Specter2** : variante du modèle (`allenai/specter2_base`, `proximity`, `classification`), exécution (locale sur CPU ou GPU, ou hébergée), persistance des vecteurs (pgvector ou fichier numpy). 74 600 publications à encoder.
- **Specter2 et le vote** : Specter2 remplace-t-il le vote, ou les deux règles se cumulent-elles ?
