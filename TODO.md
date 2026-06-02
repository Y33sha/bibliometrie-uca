* [ ] re-seeder les doi_prefix journals
# A régler avant transmission
## Schéma de données
* [ ] ajouter created_at,updated_at partout
## Pipeline de traitement
### Extraction
* [ ] hal-id non trouvé dans hal en cross-import => ajouter une phase qui supprime les hal-id erronés des external_ids?
* [ ] à étudier: cross-import: seulement in_perimeter? (ie seulement au run suivant) => éviter de cross-importer des trucs rejetés pendant la phase affiliations
* [ ] extraction par ORCID: vérifier faisabilité (quelles sources?)
* [ ] cross-import: après chaque batch, parser les externalIds des records retournés et retirer de la queue les DOI qui y figurent (éviter de multiplier les appels api pour le même document accessible par id multiples)
### Normalisation
* [ ] batcher pour améliorer la perf? / analyser pour comprendre pourquoi hal + lent
* [ ] https://hal.science/hal-03102156, https://hal.science/hal-03624131: deux fois le même auteur hal, une fois erroné: que faire? on ne devrait jamais avoir 2 fois le même hal_person_id dans une publi => lever une erreur
* [ ] vérifier espace disque avant vacuum full
### Suite du traitement
* [ ] addresses.pub_count: après phase publications, pas après normalisation.
* [ ] refresh_publication_countries: peut-on éviter de tout reset à chaque run? idem subjects / idées:  phase_cross_imports expose sources_with_new; phase_subjects : restreindre à (extract_sources ∪ sources_with_new) / phase_countries (refresh_sa_countries_for_source) : laisser scanner toutes les sources (sécurité), mais on peut envisager un addresses.updated_at en option 2 plus tard
* [ ] est-ce que les authorships détachées manuellement (donc orphelines) sont à nouveau rattachées au pipeline suivant? si oui => comportement indésirable, à corriger (ajouter rejected_authorship quand on clique sur détacher)
## Code
* [ ] organiser le dossier queries
* [ ] Unit of Work: pertinent? voir transactions multi-repos
* [ ] tests: grouper les mocks au lieu de les dupliquer d'un test à l'autre?
* [ ] page "affiliations suspectes hal": requête incorrecte, capture beaucoup trop de publis

# Chantiers qui peuvent continuer en prod (Qualité des données)
* [ ] beaucoup de résultats ScanR sont rejetés en phase "affiliations" => auditer
* [ ] normalisation des titres: supprimer les balises mml ou html
* [ ] années aberrantes dans les sources (2030): mettre null si > current_year?
## Explorer autres sources possibles
* [ ] pour les publis: ArXiv, Pubmed, Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée? récupérer pmid dans api HAL
* [ ] pour les jeux de données: DataCite, Zenodo, autres?
* [ ] divers: ORCID, IdRef, DOAJ
* [ ] OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait tenter un matching de tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA
## OA_status / embargos
* [ ] https://hal.science/hal-03874894 , https://hal.science/hal-04111614 => lien OA vers *autre* archive ouverte que HAL: en tenir compte pour le statut green
* [ ] fichiers HAL sous embargo: est-ce qu'à la fin de l'embargo le statut va se mettre à jour tout seul? (est-ce que le hash change au réimport quand l'embargo prend fin?) - je pense que oui; trouver un exemple d'embargo qui se termine prochainement et voir ce qui se passe.
* [ ] embargos (HAL, theses.fr): afficher dates dans l'UI (existent-elles dans le retour api? creuser)
## Méga-papers et alignement inter-sources
* [ ] publications > 50 auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. Approche envisagée: table `authorship_alignments` (publication_id, hal_authorship_id, oa_authorship_id, wos_authorship_id) + algorithme d'alignement par matching de noms (person_id commun → sûr, sinon Levenshtein/token overlap); en attendant, le mode "conflit de sources" dans la dédup personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`)
## Chantier des signatures institutionnelles
### Côté backend
* [ ] pays des adresses: aller plus loin dans l'automatisation de la détection (GeoNames? index n-gram des adresses avec pays associés et degré de certitude?)
* [ ] distinguer adresses correctes/incorrectes pour affichage %age par labo/personne
### Côté interface admin
* [ ] interface de repérage des adresses: ajouter filtres sur la base des autres structures reconnues dans l'adresse
* [ ] interface pour gérer les noms de pays? (actuellement table statique, rien n'y écrit)
### Côté interface publique
* [ ] Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation?

# Détails à régler au fil de l'eau (interface)
## Admin
* [ ] interface pour consulter l'audit trail
* [ ] comportement capricieux de l'UI sur la page countries (filtres qui sautent, mise à jour de l'UI à retardement): pistes de Claude: loadAddresses() est appelé sans await après le POST, donc l'ordre des promesses n'est pas garanti; Race condition FastAPI : dans le pattern engine.begin() via Depends(yield), le commit DB a lieu après que la response soit envoyée au client (doc FastAPI explicite). Donc un GET déclenché immédiatement après le POST peut voir l'état pre-commit. La parade propre serait de commit dans le handler avant return, ou de changer le pattern dep. Investigation pas anodine.
### Personnes (admin)
* [ ] quoi faire des entités fausses? a minima, rejeter leurs authorships et s'assurer qu'elles n'apparaissent pas dans orphan-authorships
* [ ] si source erronée: rejeter authorship source + recalculer affiliations de l'authorship à partir des sources non rejetées / caveat: Clarifier la sémantique de `excluded` sur les authorships sources: est-ce l'authorship qui est fausse, ou son affiliation? (allons plus loin: pourrait-on déclarer fausses certaines colonnes et pas d'autres? via un champ jsonb par exemple)
* [ ] date de dernière publication UCA? (permet de filtrer les auteurs "legacy" vs actifs)
## Publique
### Personnes (public)
* [ ] signaler publis HAL non correctement reliées au compte HAL (dans la page problèmes-hal?)
* [ ] publications: indiquer si premier/dernier auteur
### Publications
* [ ] Filtres supplémentaires possibles: langue; has_doi; corresponding_is_in_perimeter; (peer_reviewed? suppose de posséder la donnée ou de pouvoir la déduire des sources)
* [ ] avoir des groupes de pays (UE, continents) pour la recherche par facettes
* [ ] afficher mémoires master et thèses en cours sur liste publications de la page personnes/id
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses? (où se trouve la métadonnée établissement?) => ou cacher si pas de source theses.fr?
## Général (interface)
* [ ] responsivité minimale de l'interface
## Détails d'affichage
* [ ] décomptes sur les onglets: incohérents (cf nb revues par éditeur): supprimer ou corriger?
* [ ] ce serait top si le filtrage par chaîne de caractères recalculait tous les décomptes des facettes
* [ ] remplacer tag DOAJ par lien
* [ ] style barre facettes dans labos/thèses: pas homogène aux autres
* [ ] fusion revues ou modif revue: pas de mise à jour automatique de la page
* [ ] lien dashboard => publications: il faut que toutes les facettes actives soient affichées!

# Cas particuliers, bizarreries à élucider
* openalex répète des auteurs : publi 77832
* [ ] 79637: authorship source rejetée => la rejeter de l'authorship canonique
* erreur de parsing OA: publication 113652
* publi 20832: pourquoi pas d'affiliations
* 2020CLFAC007 thèse du CROC, pas récupérée via theses.fr! (158960) => aurait dû être récupéré par API theses.fr ET par cross-import de scanR via le NNT
* Eric Beyssac pas reconnu par nom dans les authorships de thèses: voir où est le problème
* Daniel Roux: 1 authorship hal, zéro publication sur sa page (ce n'est pas le seul)
* bizarrerie dans l'import crossref: fetch_missing_doi: 10325 DOI manquants pour crossref 2026-05-14 09:15:18,898 [INFO] fetch_missing_doi: 100/10325 — 101 trouvés, 100 insérés 2026-05-14 09:15:27,004 [INFO] fetch_missing_doi: 200/10325 — 202 trouvés, 200 insérés / + 800/10325 — 800 trouvés, 732 inséré : pourquoi tout n'est pas inséré?
* http://localhost:5176/bibliometrie/publications/133184 : 2 entrées "theses.fr", dont l'une redirige vers l'autre
* sujets: cooccurrences calculées sur publications, ou sur source_publications? idem nombre d'occurrences (ex.: sujet vaches laitières, 10 occurrences annoncées, 2 publications affichées)
* thèses 160226 et 132778 non fusionnées
* [ ] élucider pourquoi Openalex contient parfois beaucoup plus d'auteurs : ex. 21105 (OpenAlex semble résoudre les noms d'équipes en listes de noms de personnes, mais je ne sais pas comment)

# Trucs pour plus tard, éventuellement
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification structures? compliqué, je pense que pour ça il vaut mieux réutiliser les sources directement: contrôler seulement cohérence entre sources et corriger quand incohérent?
* audit log: uniformiser les types d'action qui génèrent un log ou pas.

# Pas nécessaire de le régler, du moment qu'on le documente
* [ ] re-tester le circuit des imports RH => pas urgent, pas d'imports csv à terme en prod
