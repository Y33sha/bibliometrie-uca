# A régler avant transmission
## Pipeline de traitement
* [ ] Faire un audit complet du logging, j'en ai marre des logs incompréhensibles ("384 déjà en staging (UPDATE SQL pour les tagger)" => WTF?) / pipeline:   51/181... (51 mis à jour, 0 déjà complets) => toujours 0 déjà complet: calculé comment? / "pipeline: CrossRef 10.1175/jas-d-25-0021.s1 sans titre ou année — pas de rattachement possible, skip" => "rattachement" en phase normalize = vestige
### Extraction
* [ ] gérer les 429 ou 503 répétés => skipper entièrement une phase
* [ ] extraction par ORCID: vérifier pertinence/faisabilité (tester différentes sources, auditer le gain)
* [ ] Paralléliser cross-imports entre eux
* [ ] à étudier: cross-import: seulement in_perimeter? (ie seulement au run n+1) => éviter de cross-importer des trucs rejetés pendant la phase affiliations
* [ ]  HAL: "0 nouveaux, 0 mis à jour, 36 inchangés" alors que j'avais nullé les hash => problème de comparaison de hash ou problème de logging?
* [ ] Comprendre pourquoi l'extract ScanR paginé est aussi lent, alors que le cross-import par DOI est ultra-rapide (2s/100 DOI contre 30s OpenAlex); ScanR est presque plus rapide par DOI que par bulk, c'est absurde
### Normalisation
* [ ] https://hal.science/hal-03102156, https://hal.science/hal-03624131: deux fois le même auteur hal, une fois erroné: que faire? on ne devrait jamais avoir 2 fois le même hal_person_id dans une publi => lever une erreur / ou juste supprimer le hal_person_id partout par précaution?
### Suite du traitement
* [ ] doi_prefixes: marquer les préfixes DOI non résolus: pas la peine de les retenter au run suivant
* [ ] phase publisher_journals: critère "stale" pour re-traiter seulement au bout de n jours? / "pipeline:   5300/7500 — 28 avec APC, 973 DOAJ, 5300 types écrits" => les données APC OpenAlex semblent très lacunaires: ne pas exploiter?
* [ ] API DOAJ: laisser tomber: inacceptablement lent, beaucoup de 404; le dump csv périodique suffit (2026-06-13 10:34:17,303 [INFO] pipeline: 11220 revues candidates (au moins un ISSN, stale > 30 jours). 2026-06-13 10:37:21,833 [INFO] pipeline:   50/11220 traités, 0 dans DOAJ, 50 404)
* [ ] phase persons: générer une liste de suggestions de fusions (conflit d'identifiants entre 2 person_id)
* [ ] phase publications: mettre un flag BOOL "deduplicated" false->true, pour empêcher les publications d'apparaître dans l'UI avant la phase déduplication?
* [ ] en fin de phase authorships, supprimer les publications sans authorship (ie hors périmètre UCA et sans auteur UCA)
## Code
* [ ] page "affiliations suspectes hal": requête incorrecte, capture beaucoup trop de publis + problème de perf
* [ ] chantier observabilité pipeline: quid des runs partiels? (phases séparées: extract, puis traitement) => ne génère pas de snapshot; c'est un problème. => faire des snapshots par phase, pas par pipeline
* [ ] Unit of Work: pertinent? voir transactions multi-repos
* [ ] DRY upsert_source_publication? (au lieu d'une fonction par source)
* [ ] Audit complet "nommage des variables". S'assurer que le code est structure-agnostique. Eviter abréviations (publication > publi > pub...). Revoir certains noms trop restrictifs (publication->document? journal->container?)
## Doc
* [ ] documenter la duplication de données (vues matérialisées, tables et colonnes dérivées) et quantifier poids vs gain de performance
* [ ] documenter les process incrémentaux vs recalcul complet et les arbitrages performance vs risque de drift; chaque process incrémental doit avoir un mode --full-rerun

# Chantiers qui peuvent continuer en prod (Qualité des données)
* [ ] beaucoup d'imports ScanR sont rejetés en phase "affiliations" => comprendre pourquoi
* [ ] années aberrantes dans les sources (2030): mettre null si > current_year?
* sujets: cooccurrences calculées sur publications, ou sur source_publications? idem nombre d'occurrences (ex.: sujet vaches laitières, 10 occurrences annoncées, 2 publications affichées)
* sujets: tenir compte du critère "in_perimeter" dans le calcul des occurrences et co-occurrences
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
* [ ] comportement capricieux de l'UI sur la page countries (filtres qui sautent, mise à jour de l'UI à retardement): pistes de Claude: "loadAddresses() est appelé sans await après le POST, donc l'ordre des promesses n'est pas garanti; Race condition FastAPI : dans le pattern engine.begin() via Depends(yield), le commit DB a lieu après que la response soit envoyée au client (doc FastAPI explicite). Donc un GET déclenché immédiatement après le POST peut voir l'état pre-commit. La parade propre serait de commit dans le handler avant return, ou de changer le pattern dep. Investigation pas anodine."
* [ ] structures: name forms: is_word_boundary devrait être false si contient séparateur de mot, même si nb cars `<` 6
### Personnes (admin)
* [ ] quoi faire des entités aberrantes (auteurs mal parsés)? a minima, s'assurer qu'elles n'apparaissent pas dans orphan-authorships
* [ ] date de dernière publication UCA? (permet de filtrer les auteurs "legacy" vs actifs)
## Publique
### Personnes (public)
* [ ] signaler publis HAL non correctement reliées au compte HAL?
* [ ] publications: indiquer si premier/dernier auteur
### Publications
* [ ] Filtres supplémentaires possibles: langue; has_doi; corresponding_is_in_perimeter; peer_reviewed? (suppose de posséder la donnée ou de pouvoir la déduire des sources);
* [ ] colonne éditeur, filtres éditeur + revue?
* [ ] avoir des groupes de pays (UE, continents) pour la recherche par facettes
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses (ajouter filtre sur "établissement de soutenance")
## Détails d'affichage
* [ ] décomptes sur les onglets: souvent incohérents à cause de requêtes légèrement différentes (cf nb revues par éditeur): supprimer ou corriger?
* [ ] ce serait top si le filtrage par chaîne de caractères recalculait tous les décomptes des facettes
* [ ] lien dashboard => publications: il faut que toutes les facettes actives soient affichées
* [ ] dashboard éditeur/revue: graphiques sur le modèle des dashboards labo/personne
* [ ] ajouter facettes sur dashboards pour générer dynamiquement les graphiques?
* [ ] double scroll dans admin/addresses: chiant
* [ ] message de chargement plutôt que "aucun résultat trouvé"

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

# Règles de correction à mettre en place
* journaux: titre terminé par " eBooks" => plateforme d'ebooks
* titre commence par "Editorial:" => type éditorial
* titre commence par "Letter:" => type lettre
* titre commence par "Systematic review" => type review
* titre contient "A systematic review" => idem

# Oneshots sur base de prod à la prochaine occasion
* vacuum full journals
* oneshot: python interfaces/cli/oneshot/refresh_publications_with_dumas_url.py
* réimporter docts openalex avec >=2 hal-ids:
```
UPDATE staging
SET raw_hash = NULL
WHERE source = 'openalex'
  AND source_id IN (
    SELECT sp.source_id
    FROM source_publications sp
    CROSS JOIN LATERAL unnest(sp.urls) AS u
    WHERE sp.source = 'openalex' AND sp.urls IS NOT NULL
    GROUP BY sp.source_id
    HAVING COUNT(DISTINCT (regexp_match(lower(u),
           '(?:hal|tel|halshs|inserm|pasteur|cea|ineris)-\d+'))[1]) >= 2
  );
```
* quid de scanr? a priori la même opération est nécessaire
* python -m interfaces.cli.oneshot.seed_place_names_from_ror (après avoir ajouter le csv dans data/)
* python -m interfaces.cli.oneshot.prune_place_names --apply
