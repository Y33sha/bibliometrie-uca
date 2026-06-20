# A régler avant transmission
## Pipeline de traitement
* [ ] Faire un audit complet du logging (complétude, clarté, cohérence entre sources et entre phases)
### Extraction
* [ ] extraction par ORCID: vérifier pertinence/faisabilité (tester différentes sources, auditer le gain)
* [ ] à étudier: cross-import: seulement `in_perimeter`? (ie seulement au run n+1) => éviter de cross-importer des trucs rejetés pendant la phase affiliations
* [ ] Comprendre pourquoi l'extract ScanR paginé est aussi lent, alors que le cross-import par DOI est ultra-rapide (2s/100 DOI contre 30s OpenAlex); ScanR est presque plus rapide par DOI que par bulk, c'est absurde (pistes: paralléliser les années d'extraction; batcher les écritures; + item suivant)
* [ ] analyser les diff de payload pour voir si on peut diminuer le nombre d'UPSERT en filtrant les champs importés (ScanR notamment)
### Suite du traitement
* [ ] DOI versionnés: déplacer la correction (suppression de suffixes) depuis `clean_doi` vers `metadata_correction`. `clean_doi` devrait se borner au nettoyage simple.
* [ ] `metadata_correction`: en cas de corrections de champs multiples sur un même doc, les règles s'appliquent indépendamment à partir du brut; étudier les scénarios de corrections multiples où l'output d'une règle pourrait intersecter l'input des suivantes, voir s'il est pertinent de les chaîner ensemble
* [ ] créer circuit pour correction automatisée du `journal_type` (titre terminé par ` eBooks` => plateforme d'ebooks)
* [ ] `metadata_correction`: ajouter correction via `doi_prefix` du journal (contrôle de cohérence entre `doi` et `journal_id`, avant les corrections `journal_type` => `doc_type`)
* [ ] conflation de doc_types différents ou titres différents sous un même DOI => soit DOI erroné, soit métadonnées erronées. Auditer et définir règles de correction
* [ ] phase `persons`: générer une liste de suggestions de fusions (conflit d'identifiants entre 2 `person_id`)
* [ ] phase `persons`: ouvrir les étapes de matching par identifiant aux `source_authorships` hors périmètre. (La garde `in_perimeter = true` est nécessaire seulement pour le matching par nom et la création.)
## Code
* [ ] page "affiliations suspectes hal": requête incorrecte, capture beaucoup trop de publis + problème de perf
* [ ] chantier observabilité pipeline: quid des runs partiels? (phases séparées: extract, puis traitement) => ne génère pas de snapshot; c'est un problème. => faire des snapshots par phase, pas par pipeline
* [ ] Unit of Work: pertinent? voir transactions multi-repos
* [ ] Audit complet "nommage des variables". S'assurer que le code est structure-agnostique. Eviter abréviations (publication > publi > pub...). Revoir certains noms trop restrictifs (publication->document? journal->container?)
## Doc
* [ ] documenter la duplication de données (vues matérialisées, tables et colonnes dérivées) et leur cycle de vie + quantifier poids vs gain de performance en lecture
* [ ] documenter les process incrémentaux (flag `dirty`) vs recalcul complet, et les arbitrages entre gain de temps et risque de drift; chaque process incrémental doit avoir un mode `--full-rebuild`

# Chantiers qui peuvent continuer en prod (Qualité des données)
* [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?
## Problèmes dans les sources
* faux auteurs UCA créés par une erreur de parsing (toutes les signatures groupées ensemble pour chaque auteur) : ex. publi 77832
* [ ] OpenAlex résout les noms d'équipes en listes de personnes (21105) => nettoyer les "for the ... study group"
* [ ] publications avec beaucoup d'auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. En attendant une solution, le mode "conflit de sources" dans la déduplication manuelle des personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`) (chantier chiant, à enterrer le plus proprement possible)
## Explorer autres sources possibles
* [ ] pour les publis: ArXiv, Pubmed, Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS?
* [ ] pour les jeux de données: DataCite, Zenodo, autres?
* [ ] divers: ORCID, IdRef, DOAJ
* [ ] OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait partir du dump complet et matcher tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA
* [ ] réévaluer l'intérêt de Crossref comme source (quelle plus-value sur les métadonnées?) - DOI Crossref non trouvés sur Crossref: quel traitement ultérieur? (signaler comme erronés? - auditer d'abord)
## Chantier des signatures institutionnelles
* [ ] Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation?
* [ ] distinguer adresses correctes/incorrectes pour affichage %age par labo/personne; suppose: 1° de définir une typologie d'erreurs, et leur caractère bloquant ou non; 2° de grouper les signatures par publi pour interroger en pourcentage de publications, non en pourcentage de signatures; 3° de restreindre aux publications *stricto sensu* (ni preprint, ni dataset etc.: définir liste blanche de doc_types à prendre en compte); 4° question des publications sans signature en base (sources HAL/ScanR seulement): exclure du calcul?

# UI
* [ ] repenser entièrement la page stats; imaginer un va-et-vient entre pages listes et pages dashboard (générés à partir de listes filtrées)
## Admin
* [ ] fusion / dé-fusion manuelle de publications: circuit à créer
* [ ] repenser entièrement les pages `admin/duplicates` et `admin/person-duplicates`
* [ ] comportement capricieux de l'UI sur la page `admin/countries` (filtres qui sautent, mise à jour de l'UI à retardement): pistes de Claude: "loadAddresses() est appelé sans await après le POST, donc l'ordre des promesses n'est pas garanti; Race condition FastAPI : dans le pattern engine.begin() via Depends(yield), le commit DB a lieu après que la response soit envoyée au client (doc FastAPI explicite). Donc un GET déclenché immédiatement après le POST peut voir l'état pre-commit. La parade propre serait de commit dans le handler avant return, ou de changer le pattern dep. Investigation pas anodine."
### Personnes (admin)
* [ ] quoi faire des entités aberrantes (auteurs mal parsés)? *a minima*, s'assurer qu'elles n'apparaissent pas dans `admin/orphan-authorships`
## Publique
### Personnes (public)
* [ ] publications: indiquer si premier/dernier auteur
### Publications
* [ ] Filtres supplémentaires possibles: langue; `has_doi` (crossref, datacite, other, none); `corresponding_is_in_perimeter`; `peer_reviewed`? (suppose de posséder la donnée ou de pouvoir la déduire des sources); licence
* [ ] colonne éditeur; filtres éditeur + revue?
* [ ] définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses (ajouter filtre implicite sur "établissement de soutenance" / ou le faire en amont dès le pipeline?)
## Détails d'affichage
* [ ] dashboard éditeur/revue: graphiques sur le modèle des dashboards labo/personne
* [ ] ajouter facettes sur dashboards pour générer dynamiquement les graphiques?
* [ ] tableau laboratoires: séparer colonnes acronyme et nom; trier par acronyme; rétrécir colonne tutelles

# Cas particuliers, bizarreries à élucider
* Daniel Roux: 1 authorship hal, zéro publication sur sa page (ce n'est pas le seul)
* [ ] 151499: source primaire HAL d'après Openalex mais pas de document HAL en base

# Trucs pour plus tard, éventuellement
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification des structures partenaires?
* audit trail: uniformiser les types d'action qui génèrent un log ou pas + interface pour les consulter
* règles de correction de métadonnées et règles de déduplication de publications: actuellement logées dans le code; possibilité de les stocker en base et de les rendre configurables via l'UI?
* rendre les extracteurs interruptibles avec ctrl+C sous Windows

# Pas nécessaire de le régler, du moment qu'on le documente
* [ ] re-tester le circuit des imports RH => pas urgent, pas d'imports csv à terme en prod
