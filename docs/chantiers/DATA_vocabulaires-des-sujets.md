# Vocabulaires des sujets

## Contexte

Base locale au 2026-11-01.

- **Unicité des sujets.** `subjects` contient un libellé par sujet, unique à la casse près. Les fonctions de lecture des sujets (`subject_extractors.py`) rendent des libellés seuls. Un libellé présent dans plusieurs vocabulaires donne un seul sujet : 3 001 libellés au 2026-10-25. Les homonymes d'un même vocabulaire aussi : « Biochemistry », « Genetics », « Pharmacology » sont des subfields OpenAlex de deux fields différents ; « Social Sciences » est domain et field.
- **Hiérarchie.** Tous les niveaux sont liés à plat à la publication. La chaîne domain → field → subfield → topic d'OpenAlex et le chemin des domaines HAL existent seulement dans `source_records.topics`.
- **Codes des vocabulaires.**
  - OpenAlex : le payload donne l'identifiant de chaque niveau (`domains/2`, `fields/20`, `subfields/2002`, `T11257`). Le normalizer garde le libellé et le score seulement (`extract_topics`).
  - Domaines HAL : `topics.hal_domains` garde le code de la feuille (`sdv.bbm.bm`). Le code de chaque ancêtre en est un préfixe.
  - RAMEAU : chaque vedette a un PPN, vedettes construites comprises (« Béton armé -- Fissuration »). ScanR le garde dans `topics`. theses.fr le donne dans le champ `query` de `mapSujets`, et le normalizer l'écarte. Les PPN des deux sources concordent pour 2 557 des 2 558 libellés communs. Chez ScanR, 51 PPN ont deux formes d'une même vedette (« Poumon -- Cancer », « Cancer du poumon »).
  - Discipline de theses.fr : libellé libre, 471 distincts.
- **Raw store.** Il est complet pour OpenAlex (116 813 payloads pour 116 331 enregistrements sources), presque complet pour HAL (66 523 pour 67 303). Pour theses.fr, il compte 2 670 payloads pour 3 912 enregistrements sources, dont 2 636 au format de la liste de résultats de la recherche, illisible par le normalizer.
- **MeSH.** Aucun sujet MeSH. Le moissonnage OpenAlex omet le champ `mesh` des works (`pipeline/ingestion/openalex/api.py`). PubMed n'est pas moissonné.
- **Besoins de l'interface.** Les nuages de sujets (`SubjectsCloud.svelte`) et le graphe des co-occurrences (`/subjects/[id]`) colorent par fréquence. Ils demandent une couleur par grand domaine, et de pouvoir écarter les niveaux hauts, qui encombrent sans informer.
- **`publications_detail.topics`** copie les `topics` des enregistrements sources de chaque publication. Aucune page ni aucune phase ne la lit.
- **Mots-clés HAL.** Le normalizer HAL lit `keyword_s`, qui perd les parenthèses : « eau destinée à la consommation humaine (EDCH) » devient « Eau destinée à la consommation humaine EDCH ».

## Décisions

- **Code et hiérarchie.** Un sujet est identifié par son vocabulaire et son code dans ce vocabulaire, à défaut son libellé. Il a un niveau et un parent.
- **Une seule table de sujets.** `subjects` contient le vocabulaire, le code, le niveau et le parent ; `publication_subjects` relie les publications à ces sujets. Les vedettes RAMEAU, identifiées par leur PPN chez ScanR comme chez theses.fr, forment un seul sujet quelle que soit la source.
- **Les codes précèdent le schéma.** Les normalizers écrivent les codes dans `source_records.topics`, et le stock est mis en conformité, avant que l'ingestion identifie les sujets par leur code. Chaque sujet OpenAlex ou RAMEAU est ainsi identifié par son code dès sa première ingestion.
- **Sujets WoS abandonnés.** Ils sont les seuls sujets de 558 publications (0,7 %), presque toutes présentes seulement dans le WoS : résumés de congrès, articles sans enregistrement OpenAlex.
- **Couleurs.** Les domaines de haut niveau de tous les vocabulaires partagent une palette commune.
- **Les 4 domains OpenAlex sont écartés des graphiques.**

## Phasage

### Phase 1 — Correctifs indépendants

- [ ] Normalizer HAL : mots-clés lus dans les `<term>` du TEI (`label_xml`), `keyword_s` à défaut
- [ ] Stock HAL : script ponctuel qui relit les mots-clés TEI dans le raw store
- [ ] Retrait de `publications_detail.topics` et de `Publication.topics`

### Phase 2 — Codes dans les enregistrements sources

- [ ] Normalizer OpenAlex : `extract_topics` garde l'identifiant de chaque niveau
- [ ] Normalizer theses.fr : chaque vedette RAMEAU garde son PPN ; fonction de lecture des sujets theses.fr adaptée au format de `topics`
- [ ] Stock OpenAlex : script ponctuel qui réécrit `topics` depuis le raw store
- [ ] Stock theses.fr : script ponctuel qui relit le détail de chaque thèse dans theses.fr et réécrit `topics`. Il retire aussi `source_extras.discipline`

### Phase 3 — Sujets identifiés par vocabulaire et code

- [ ] Schéma : `subjects` contient vocabulaire, code, niveau et parent ; unicité sur (vocabulaire, code) à la place de l'unicité sur le libellé. Livré avec les fonctions de lecture et l'ingestion
- [ ] Fonctions de lecture des sujets (`subject_extractors.py`) : chaque sujet rendu avec son vocabulaire, son code, son niveau et son parent. Codes : celui des domaines HAL, identifiants OpenAlex, PPN des vedettes RAMEAU, libellé de la discipline de theses.fr. Lecture des sujets WoS retirée
- [ ] Ingestion de la phase `subjects` par (vocabulaire, code) ; reconstruction du stock
- [ ] API des sujets : vocabulaire et niveau de chaque sujet
- [ ] Documentation : `docs/agregats/subjects.md`, `docs/donnees/03-publications.md`

### Phase 4 — MeSH

- [ ] Moissonnage selon la source retenue
- [ ] Lecture des sujets MeSH : descripteur identifié par son code, avec son niveau et son parent

### Phase 5 — Couleurs dans l'interface

- [ ] Rattachement des domaines de haut niveau de chaque vocabulaire à la palette commune : codes HAL, mots-clés des disciplines theses.fr (correspondances de `prototype_subject_vote`)
- [ ] API : classe de couleur de chaque sujet des nuages et du graphe des co-occurrences
- [ ] Nuages de sujets et graphe des co-occurrences : couleur par classe, légende ; domains OpenAlex écartés
- [ ] Guide utilisateur : sens des couleurs

## Questions ouvertes

- **Source du MeSH** : champ `mesh` d'OpenAlex, renseigné pour les publications indexées dans PubMed, ou moissonnage de PubMed. Un descripteur MeSH occupe plusieurs positions dans l'arborescence : `subjects` lui donne un seul parent.
- **Parents des vedettes RAMEAU** : termes génériques lus dans IdRef, ou aucun parent.
- **Libellé d'un sujet différent selon les sources** : 51 PPN RAMEAU à deux libellés chez ScanR.
- **Classes de la palette commune.** Les correspondances du prototype de vote rattachent des codes HAL et des disciplines à plusieurs domains OpenAlex (`sdv.neu` : Health et Life ; `scco` : Social Sciences, Life et Health). Une couleur par sujet demande une seule classe.
- **Doublons à l'affichage** : une cinquantaine de libellés communs à deux vocabulaires (« Informatique », domaine HAL et discipline de thèse), et des homonymes internes à OpenAlex (« Biochemistry », subfield de deux fields). À regrouper à l'affichage s'ils gênent.
- **Niveaux écartés des graphiques** au-delà des domains OpenAlex : fields, premier niveau HAL.
