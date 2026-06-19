python -m interfaces.cli.oneshot.renormalize_escaped_titles
# A régler avant transmission
## Pipeline de traitement
* [ ] Faire un audit complet du logging, j'en ai marre des logs incompréhensibles ("384 déjà en staging (UPDATE SQL pour les tagger)" => WTF?) / "pipeline: CrossRef 10.1175/jas-d-25-0021.s1 sans titre ou année — pas de rattachement possible, skip" => "rattachement" en phase normalize = vestige / cross-import: "Échec après 3 tentatives rec 1 / 429 Too Many Requests rec 1 — attente 4.0s (tentative 1/3)" => toujours préciser la source qui échoue
* [ ] peut-on ajouter des commandes clavier? (abandonner phase, passer à la suivante)
### Extraction
* [ ] extraction par ORCID: vérifier pertinence/faisabilité (tester différentes sources, auditer le gain)
* [ ] à étudier: cross-import: seulement in_perimeter? (ie seulement au run n+1) => éviter de cross-importer des trucs rejetés pendant la phase affiliations
* [ ] HAL: "0 nouveaux, 0 mis à jour, 36 inchangés" alors que j'avais nullé les hash => problème de comparaison de hash ou problème de logging?
* [ ] Comprendre pourquoi l'extract ScanR paginé est aussi lent, alors que le cross-import par DOI est ultra-rapide (2s/100 DOI contre 30s OpenAlex); ScanR est presque plus rapide par DOI que par bulk, c'est absurde
* [ ] cross-import par NNT: " 300/332 — 0 récupérés, 297 absents de HAL" quid des 3 autres?
### Normalisation
* [ ] https://hal.science/hal-03102156, https://hal.science/hal-03624131: deux fois le même auteur hal, une fois erroné: que faire? on ne devrait jamais avoir 2 fois le même hal_person_id dans une publi => lever une erreur / ou juste supprimer silencieusement le hal_person_id partout par précaution (problème: empêche de détecter l'erreur pour la corriger dans HAL) / ou détecter en phase "persons" et empêcher la propagation des identifiants
### Suite du traitement
* [ ] créer circuit pour correction automatisée des journal_types (titre terminé par " eBooks" => plateforme d'ebooks)
* [ ] metadata_correction: ajouter correction via doi_prefix du journal (contrôle de cohérence entre doi et journal_id, avant les corrections journal_type => doc_type)
* [ ] phase persons: générer une liste de suggestions de fusions (conflit d'identifiants entre 2 person_id)
## Code
* [ ] page "affiliations suspectes hal": requête incorrecte, capture beaucoup trop de publis + problème de perf
* [ ] chantier observabilité pipeline: quid des runs partiels? (phases séparées: extract, puis traitement) => ne génère pas de snapshot; c'est un problème. => faire des snapshots par phase, pas par pipeline
* [ ] Unit of Work: pertinent? voir transactions multi-repos
* [ ] DRY upsert_source_publication? (au lieu d'une fonction par source)
* [ ] Audit complet "nommage des variables". S'assurer que le code est structure-agnostique. Eviter abréviations (publication > publi > pub...). Revoir certains noms trop restrictifs (publication->document? journal->container?)
## Doc
* [ ] documenter la duplication de données (vues matérialisées, tables et colonnes dérivées) et leur refresh + quantifier poids vs gain de performance en lecture
* [ ] documenter les process incrémentaux (flag *dirty*) vs recalcul complet, et les arbitrages entre gain de temps et risque de drift; chaque process incrémental doit avoir un mode --full-rebuild

# Chantiers qui peuvent continuer en prod (Qualité des données)
* [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?
## Explorer autres sources possibles
* [ ] pour les publis: ArXiv, Pubmed, Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée?
* [ ] pour les jeux de données: DataCite, Zenodo, autres?
* [ ] divers: ORCID, IdRef, DOAJ
* [ ] OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait tenter un matching de tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA
* [ ] réévaluer l'intérêt de Crossref comme source (quelle plus-value sur les métadonnées?) - DOI Crossref non trouvés sur Crossref: quel traitement ultérieur? (signaler comme erronés? - auditer d'abord);
## Méga-papers et alignement inter-sources
* [ ] publications avec beaucoup d'auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. En attendant une solution, le mode "conflit de sources" dans la déduplication manuelle des personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`) (chantier chiant, à enterrer le plus proprement possible)
## Chantier des signatures institutionnelles
* [ ] distinguer adresses correctes/incorrectes pour affichage %age par labo/personne
* [ ] Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation?

# UI
* [ ] repenser entièrement la page stats; imaginer un va-et-vient entre pages listes et pages dashboard (générés à partir de listes filtrées)
* [ ] gérer les warnings vite-plugin-svelte
## Admin
* [ ] fusion / dé-fusion manuelle de publications: circuit à créer
* [ ] comportement capricieux de l'UI sur la page admin/countries (filtres qui sautent, mise à jour de l'UI à retardement): pistes de Claude: "loadAddresses() est appelé sans await après le POST, donc l'ordre des promesses n'est pas garanti; Race condition FastAPI : dans le pattern engine.begin() via Depends(yield), le commit DB a lieu après que la response soit envoyée au client (doc FastAPI explicite). Donc un GET déclenché immédiatement après le POST peut voir l'état pre-commit. La parade propre serait de commit dans le handler avant return, ou de changer le pattern dep. Investigation pas anodine."
* [ ] structures_name_forms: is_word_boundary devrait être forcé à false si contient séparateur de mot, même si nb cars `<` 6 (? vérifier d'abord l'effet réel de is_word_boundary)
### Personnes (admin)
* [ ] quoi faire des entités aberrantes (auteurs mal parsés)? a minima, s'assurer qu'elles n'apparaissent pas dans orphan-authorships
* [ ] date de dernière publication UCA? (permet de filtrer les auteurs "legacy" vs actifs)
## Publique
### Personnes (public)
* [ ] signaler publis HAL non correctement reliées au compte HAL?
* [ ] publications: indiquer si premier/dernier auteur
### Publications
* [ ] Filtres supplémentaires possibles: langue; has_doi (crossref, datacite, other, none); corresponding_is_in_perimeter; peer_reviewed? (suppose de posséder la donnée ou de pouvoir la déduire des sources);
* [ ] colonne éditeur, filtres éditeur + revue?
* [ ] avoir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses (ajouter filtre implicite sur "établissement de soutenance")
## Détails d'affichage
* [ ] décomptes sur les onglets: souvent incohérents à cause de filtres différents (cf nb revues par éditeur): supprimer ou corriger?
* [ ] ce serait top si le filtrage par chaîne de caractères recalculait tous les décomptes des facettes
* [ ] lien dashboard => publications: il faut que TOUTES les facettes actives soient affichées
* [ ] dashboard éditeur/revue: graphiques sur le modèle des dashboards labo/personne
* [ ] ajouter facettes sur dashboards pour générer dynamiquement les graphiques?
* [ ] champ recherche de la page sujets: sensible aux accents; corriger et auditer tous les autres

# Cas particuliers, bizarreries à élucider
* openalex répète des auteurs : publi 77832
* erreur de parsing OA: publication 113652
* publi 20832: pourquoi pas d'affiliations
* 2020CLFAC007 thèse du CROC, pas récupérée via theses.fr! (158960) => aurait dû être récupéré par API theses.fr ET par cross-import de scanR via le NNT
* Eric Beyssac pas reconnu par nom dans les authorships de thèses: voir où est le problème
* Daniel Roux: 1 authorship hal, zéro publication sur sa page (ce n'est pas le seul)
* bizarrerie dans l'import crossref: fetch_missing_doi: 10325 DOI manquants pour crossref 2026-05-14 09:15:18,898 [INFO] fetch_missing_doi: 100/10325 — 101 trouvés, 100 insérés 2026-05-14 09:15:27,004 [INFO] fetch_missing_doi: 200/10325 — 202 trouvés, 200 insérés / + 800/10325 — 800 trouvés, 732 inséré : pourquoi tout n'est pas inséré?
* http://localhost:5176/bibliometrie/publications/133184 : 2 entrées "theses.fr", dont l'une redirige vers l'autre
* thèses 160226 et 132778 non fusionnées
* [ ] élucider pourquoi Openalex contient parfois beaucoup plus d'auteurs : ex. 21105 (OpenAlex semble résoudre les noms d'équipes en listes de noms de personnes, mais je ne sais pas comment)
* 52083 => pourquoi type data paper?

# Trucs pour plus tard, éventuellement
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification des structures partenaires?
* audit trail: uniformiser les types d'action qui génèrent un log ou pas + interface pour les consulter
* règles de correction de métadonnées et règles de déduplication de publications: actuellement logées dans le code; possibilité de les stocker en base et de les rendre configurables via l'UI?

# Pas nécessaire de le régler, du moment qu'on le documente
* [ ] re-tester le circuit des imports RH => pas urgent, pas d'imports csv à terme en prod
