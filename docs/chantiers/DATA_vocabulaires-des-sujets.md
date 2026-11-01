# Vocabulaires des sujets

## Contexte

Base locale au 2026-11-01.

- **Unicité des sujets.** Un sujet identifié par son seul libellé réunit les vocabulaires : 3 001 libellés communs à plusieurs vocabulaires au 2026-10-25. Les homonymes d'un même vocabulaire aussi : « Biochemistry », « Genetics », « Pharmacology » sont des subfields OpenAlex de deux fields différents ; « Social Sciences » est domain et field.
- **Hiérarchie.** Tous les niveaux sont liés à plat à la publication. La chaîne domain → field → subfield → topic d'OpenAlex et le chemin des domaines HAL existent seulement dans `source_records.topics`.
- **Codes des vocabulaires.**
  - OpenAlex : le payload donne l'identifiant de chaque niveau (`domains/2`, `fields/20`, `subfields/2002`, `T11257`). Le normalizer garde le libellé et le score seulement (`extract_topics`).
  - Domaines HAL : `topics.hal_domains` garde le code de la feuille (`sdv.bbm.bm`). Le code de chaque ancêtre en est un préfixe.
  - RAMEAU : chaque vedette a un PPN, vedettes construites comprises (« Béton armé -- Fissuration »). ScanR le garde dans `topics`. theses.fr le donne dans le champ `query` de `mapSujets`, et le normalizer l'écarte. Les PPN des deux sources concordent pour 2 557 des 2 558 libellés communs. Chez ScanR, 51 PPN ont deux formes d'une même vedette (« Poumon -- Cancer », « Cancer du poumon »).
  - Discipline de theses.fr : libellé libre, 644 distincts à la casse et aux accents près. La discipline de 1 090 thèses sur 3 912 coïncide avec une vedette RAMEAU (« Informatique », « Mathématiques »). Les autres disciplines sont composées (« Biologie santé », « Mécanique, génie mécanique, génie civil »).
- **Raw store.** Il est complet pour OpenAlex : 116 813 payloads pour 116 331 enregistrements sources.
- **MeSH.** Aucun sujet MeSH. Le moissonnage OpenAlex omet le champ `mesh` des works (`pipeline/ingestion/openalex/api.py`). PubMed n'est pas moissonné. Chaque entrée de `mesh` contient l'identifiant du descripteur (`D008175`), son libellé, un qualificatif facultatif (`Q000453`, « epidemiology ») et un indicateur de sujet majeur. Les numéros d'arborescence sont absents.
- **Besoins de l'interface.** Les nuages de sujets (`SubjectsCloud.svelte`) et le graphe des co-occurrences (`/subjects/[id]`) demandent de pouvoir écarter les niveaux hauts, qui encombrent sans informer.
- **Mots-clés HAL.** Le champ Solr `keyword_s` met une majuscule initiale et retire la ponctuation : « Industry 4.0 » devient « Industry 40 », « eau destinée à la consommation humaine (EDCH) » devient « Eau destinée à la consommation humaine EDCH ». Les `<term>` du TEI (`label_xml`) gardent la saisie de l'auteur. Ils sont présents dans chaque dépôt pourvu de `keyword_s`, sur un échantillon de 4 160 dépôts.

## Décisions

- **Code et hiérarchie.** Un sujet est identifié par son vocabulaire et son code dans ce vocabulaire. Le code d'une discipline de thèse est son libellé normalisé. Un sujet a un niveau et un parent.
- **Une seule table de sujets.** `subjects` contient le vocabulaire, le code, le libellé, le niveau et le parent. La langue du libellé découle du vocabulaire. Les vedettes RAMEAU, identifiées par leur PPN chez ScanR comme chez theses.fr, forment un seul sujet quelle que soit la source.
- **Sujets écrits à la normalisation.** La clé (vocabulaire, code) se passe de résolution entre sources, comme celle des adresses. Le normalizer de chaque source écrit donc les sujets donnés par la source dans `subjects`, et leurs liens dans `source_record_subjects`, avec le score OpenAlex. La phase `subjects` dérive `publication_subjects` en SQL, ancêtres compris. `source_records.topics` disparaît.
- **Sujets WoS abandonnés.** Ils sont les seuls sujets de 558 publications (0,7 %), presque toutes présentes seulement dans le WoS : résumés de congrès, articles sans enregistrement OpenAlex.
- **MeSH lu dans OpenAlex.** Le champ `mesh` des works donne les descripteurs des publications indexées dans PubMed.
- **Sujets regroupés par libellé.** Les sujets de même libellé normalisé forment un seul sujet affiché, tous vocabulaires confondus. « Chimie » réunit le domaine HAL, la vedette RAMEAU et la discipline de thèse. Son nombre de publications est l'union de leurs publications. Liste, page d'un sujet, filtre, nuages et co-occurrences portent sur ce regroupement. La page d'un sujet montre chaque vocabulaire, avec parents et enfants.
- **Une vue matérialisée.** Rafraîchie par la phase `subjects`, elle contient une ligne par libellé normalisé : la forme la plus fréquente du libellé et le nombre de publications. Le libellé normalisé identifie le sujet dans l'URL.
- **Les 4 domains OpenAlex sont écartés des graphiques.**

## Phasage

### Phase 1 — Correctifs indépendants

- [x] Normalizer HAL : mots-clés lus dans les `<term>` du TEI
- [x] `keyword_s` retiré des champs demandés à l'API. L'empreinte de chaque payload HAL change : chaque dépôt relu est normalisé une fois de plus
- [x] Retrait de `publications_detail.topics` et de `Publication.topics` (e227269d1)

### Phase 2 — Sujets écrits à la normalisation

- [x] Schéma : `subjects` contient vocabulaire, code, niveau et parent ; unicité sur (vocabulaire, code) à la place de l'unicité sur le libellé ; `language` retirée. Table `source_record_subjects` : enregistrement source, sujet, score (9b2ed7d01)
- [x] Écriture commune aux normalizers : sujets et liens en une requête par lot
- [x] HAL : domaines par leur code, chaque niveau rattaché au niveau supérieur
- [x] OpenAlex : identifiant de chaque niveau, score du topic
- [x] ScanR et theses.fr : vedettes RAMEAU par leur PPN, lu dans le champ `query` chez theses.fr ; discipline de theses.fr par son libellé
- [x] WoS : sujets abandonnés
- [x] Phase `subjects` : `publication_subjects` dérivée en SQL de `source_record_subjects` ; fonctions de lecture des sujets (`subject_extractors.py`) retirées
- [x] Fiche d'une thèse : discipline lue dans les sujets
- [x] API des sujets : vocabulaire et niveau de chaque sujet
- [x] Documentation : `docs/donnees/03-publications.md`, `docs/pipeline/03-normalize.md`, `docs/pipeline/11-enrichissements.md`

### Phase 3 — Stock, entre la migration et le run suivant

- [x] Script ponctuel `write_source_record_subjects` : HAL et ScanR depuis `source_records.topics`, où les codes sont présents (b0b93124e)
- [x] Même script : OpenAlex et ScanR depuis le raw store, enregistrements sources sans sujet seulement (a6317415c)
- [x] Retrait de `source_records.topics` ; scripts de la pertinence des sujets (`sample_subject_relevance`, `prototype_subject_vote`) adaptés (ac2de2b5d)
- [x] theses.fr : `raw_hash` vidé et `last_seen_at` vieilli pour toutes les thèses, puis `fetch_stale`. La normalisation qui suit retire aussi `source_extras.discipline`
- [x] HAL : `last_seen_at` vieilli pour tous les dépôts, puis run. Le moissonnage relit les dépôts des collections, `fetch_stale` les autres. Leur normalisation écrit les mots-clés du TEI

### Phase 4 — MeSH

- [ ] `mesh` ajouté aux champs demandés à OpenAlex. L'empreinte de chaque payload OpenAlex change : chaque work relu est normalisé une fois de plus
- [ ] Normalizer : descripteurs MeSH identifiés par leur code, avec leur niveau et leur parent

### Phase 5 — Sujets regroupés par libellé

- [x] Migration : vue matérialisée des libellés normalisés (`subject_labels`) ; `subject_cooccurrences` entre libellés normalisés (d6db5fc18)
- [x] Phase `subjects` : rafraîchissement des deux vues
- [x] API : liste et export par libellé, avec les vocabulaires de chaque libellé ; détail d'un libellé avec les sujets de chaque vocabulaire, leurs parents, leurs enfants et les voisins par co-occurrence
- [x] Filtre des publications par sujet, facette et nuages de sujets : par libellé normalisé
- [x] Frontend : liste, page d'un sujet, liens des fiches de publications et des nuages
- [x] Liste des sujets : facette des vocabulaires
- [x] Documentation : `docs/donnees/03-publications.md`, `docs/pipeline/11-enrichissements.md`, guide utilisateur

## Questions ouvertes

- **Parents des descripteurs MeSH** : arborescence publiée par la NLM, ou aucun parent. Un descripteur occupe plusieurs positions dans l'arborescence : `subjects` lui donne un seul parent.
- **Qualificatifs MeSH** : écartés, ou sujets à part.
- **Descripteurs démographiques MeSH** (« Humans », « Male », « Female », « Aged ») : présents sur la plupart des publications médicales.
- **Indicateur de sujet majeur** : score du lien, ou écarté.
- **Parents des vedettes RAMEAU** : termes génériques lus dans IdRef, ou aucun parent.
- **Libellé d'un sujet différent selon les sources** : 51 PPN RAMEAU à deux libellés chez ScanR.
- **Libellés OpenAlex en anglais** : 7 coïncident avec un autre vocabulaire. Sujets OpenAlex à part, ou traduction des niveaux hauts (4 domains, 26 fields, 250 subfields).
- **Niveaux écartés des graphiques** au-delà des domains OpenAlex : fields, premier niveau HAL.
