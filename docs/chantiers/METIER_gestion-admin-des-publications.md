# Chantier — Gestion des publications dans l'administration

## Contexte

**Menu d'administration.** Le menu « Référentiels » donne accès aux structures, aux personnes, aux éditeurs et aux revues. Les publications n'y figurent pas. Une entrée séparée, « Dédoublonnage », mène à `admin/duplicates`.

**La page `admin/duplicates`** présente une à une des paires de publications candidates à la fusion. Une paire partage le même titre normalisé (au-delà d'une longueur minimale), sans deux DOI différents, sans que les deux publications contiennent chacune un enregistrement source HAL, OpenAlex ou WoS, et hors des paires déclarées distinctes. Deux actions : fusionner (`POST /api/publications/duplicates/merge`, service `merge_publications`) et déclarer distinctes (`POST /api/publications/duplicates/mark-distinct`, table `distinct_publications`). Pièces : la route (375 lignes), trois points d'entrée de l'API, la lecture `infrastructure/read_models/publications/duplicates.py` et son port `PublicationDuplicatesQueries`, le client `#lib/api/duplicates.ts`.

**Ces deux actions ne sont pas durables.** La phase `publications` regroupe à chaque passage les enregistrements sources qui partagent une clé de confirmation, dans le voisinage des enregistrements sources modifiés. Une publication à cheval sur deux groupes est scindée. Une fusion manuelle entre publications sans clé commune est donc défaite dès que le voisinage de l'un de leurs enregistrements sources est recalculé. La table `distinct_publications` n'est pas lue par le pipeline.

**Le référentiel Personnes sert de modèle.** La page `admin/persons` comporte des onglets : la liste, puis quatre files de triage avec leur compteur. Un clic ouvre un volet droit (`?person=<id>` dans l'URL), large de 480 pixels au plus. Les verdicts qui s'y prennent — formes de nom rejetées, contributions sources détachées, personnes déclarées distinctes — sont des entrées que le pipeline relit à chaque passage.

**La comparaison des sources** vit dans la page publique d'une publication (`publications/[id]/SourceComparison.svelte`, 501 lignes), réservée à l'administration connectée. Elle aligne les auteurs par position pour quatre sources codées en dur : HAL, OpenAlex, WoS, ScanR. La réponse de l'API (`PublicationDetailResponse`) contient une liste de contributions sources par source nommée (`hal_contributions`, `openalex_contributions`…) : Crossref et DataCite n'y figurent pas.

**Une conception antérieure** esquisse des « contrôles admin » sur le modèle opt-out : le pipeline fusionne d'office, l'administration contrôle a posteriori.
- Détecteur de fusions suspectes : recouvrement d'auteurs faible ou nul, titre court ou générique, `container_title` divergent pour les chapitres, groupe anormalement gros.
- Verdicts ancrés sur les `source_records`, jamais sur les `publications`, dont l'identifiant change à chaque réconciliation : un discriminant de scission (valeurs différentes ⇒ jamais dans le même groupe) et un jeton de fusion forcée (valeur commune ⇒ même groupe), branchés sur les mécanismes de regroupement existants.

**Fusion erronée par une déclaration DataCite.** Une copie de repository du DESY (`10.3204/pubdb-2019-03026`) concerne la production de paires de squarks bottom. Elle déclare `IsVariantFormOf` vers un article sur la production W±Z (`10.1140/epjc/s10052-019-7027-6`). La correction des métadonnées lui donne le DOI de cet article, donc elle rejoint sa publication.

**Volumétrie des quatre détecteurs**, mesurée sur 63 164 publications et 255 267 enregistrements sources, dont 60 257 groupes de deux enregistrements sources ou plus.

- *Recouvrement d'auteurs* : 381 groupes dont deux enregistrements sources ne partagent aucun mot de nom d'auteur, 492 sous 20 % de recouvrement. Parmi les 381, 65 opposent un collectif (`collaboration`, `consortium`, le substitut `UNAP` de DataCite) à une liste de noms, et 278 un collectif ou un enregistrement source réduit à un seul nom.
- *Taille du groupe* : les `dataset` et les `software` occupent la queue de distribution, jusqu'à 1198 enregistrements sources sous un seul DOI. Recherche Data Gouv et Zenodo émettent un DOI de collection que chaque pièce d'un jeu de données réutilise, et OpenAlex crée un enregistrement source par pièce. Hors ces deux types, 136 groupes atteignent 8 enregistrements sources, dont 45 `conference_paper` et 42 `article`.
- *Conteneur divergent des chapitres* : 214 chapitres comparables une fois écarté l'artefact décrit ci-dessous, dont 57 sous 20 % de similarité trigramme.
- *Titres identiques* : 2 424 titres partagés par 5 063 publications, dont 131 titres sans aucune publication à DOI.

**OpenAlex renseigne `container_title` avec le nom du repository** pour 17 345 enregistrements sources, plus de la moitié de ceux où il fournit un conteneur : « HAL (Le Centre pour la Communication Scientifique Directe) ». Le volet affiche cette valeur, et un détecteur fondé sur le conteneur la remonte. Relève de la correction des métadonnées, hors du périmètre de ce chantier.

**Les dépôts HAL des articles de The Conversation** omettent souvent le DOI et ajoutent « The Conversation » au titre. 25 dépôts HAL sans DOI ont un titre qui commence par celui d'un article The Conversation (préfixe `10.64628`) rattaché à une autre publication. Retirer ce suffixe relève de la correction des métadonnées, hors du périmètre de ce chantier.

## Décisions

- **Une page `admin/publications`**, dans le menu « Référentiels », affiche la liste des publications de la page publique (`PublicationsListView`), inchangée.
- **Un clic sur une publication ouvre un volet droit**, comme dans le référentiel Personnes, bien plus large : il sert à confronter toutes les métadonnées des sources.
- **Des onglets**, comme dans le référentiel Personnes, accueillent la détection automatisée des fusions suspectes.
- **La page `admin/duplicates` et son entrée de menu disparaissent.**
- **Le premier détecteur mesure le recouvrement des noms d'auteurs** entre les enregistrements sources d'un même groupe.
- **La taille du groupe ne fait pas un signal par elle-même.** Un jeu de données de plusieurs centaines de pièces se regroupe correctement. Le signal reste à évaluer hors `dataset` et `software`.
- **Les titres identiques ne font pas une file de triage** : 5 063 publications, sans discriminant.
- **Les verdicts s'ancrent sur la clé naturelle `(source, source_id)` des enregistrements sources** : elle survit à la suppression puis à la réapparition d'un enregistrement source.
- **Une fusion forcée pose un jeton de fusion** sur tous les enregistrements sources des deux publications. La réconciliation lit ce jeton comme une clé de confirmation. Il équivaut aux arêtes affirmées de CRISalid (voir le [benchmark](archived/2026-10-12_benchmark-pipelines.md)).
- **La fusion forcée est refusée entre deux publications à DOI distincts**, en vertu de la règle « un DOI, une œuvre ». Ces cas relèvent d'une correction de DOI.
- **La fusion forcée prend effet immédiatement**, comme la fusion des revues, des éditeurs et des personnes. Les sujets, les pays, le statut OA et les relations suivent au prochain passage du pipeline.
- **Veto sur le lien entre une contribution source et une structure.** Un auteur parti garde dans HAL une affiliation obsolète. Sa contribution source HAL fait entrer dans le périmètre une publication faite ailleurs. La personne est bien l'auteur, et du périmètre pour d'autres publications : le rejet du lien personne–publication et l'exclusion de la personne sont inadaptés. Le veto vise le lien entre la contribution source et la structure, stable dans le temps. Un groupe de contributions sources est recalculé à chaque passage.

## Phasage

### 1. Page et liste

- [x] Route `admin/publications`, entrée « Publications » dans le menu « Référentiels » (a85c42ed).
- [x] Liste des publications (a85c42ed).
- [x] Emplacement des onglets, avec la liste pour premier onglet : composant `HubTabs`, partagé avec le référentiel Personnes (13b4ed89).
- [x] Suppression de `admin/duplicates`, de son entrée de menu, et de la lecture des paires candidates (point d'entrée, port, adaptateur, tests, doc) (a85c42ed).
- [x] Suppression de la fusion et de la distinction manuelles, sans effet durable : points d'entrée, client, services, erreur `DistinctDoiError`, table `distinct_publications` (b52fb3d6).

### 2. Volet

- [x] Volet droit ouvert par `?publication=<id>`, fermé par Échap et par le fond : composant `Drawer`, partagé avec le référentiel Personnes (6736ac39).
- [x] Métadonnées de chaque enregistrement source, confrontées, une colonne par enregistrement source : identifiants, titre, type, année, revue et ISSN, éditeur, conteneur, volume, numéro, pages, langue, statut OA (6736ac39).
- [x] Lecture de l'API qui rend les enregistrements sources d'une publication, toutes sources confondues, sans champ nommé par source (6736ac39).

### 3. Détection des fusions suspectes

Prérequis : phase 3 du chantier [alignement des auteurs](archived/2026-10-24_DATA_alignement-auteurs.md). La mesure du recouvrement porte sur les auteurs alignés.

- [x] Onglet « Fusions suspectes » et son compteur : publications dont moins de la moitié des auteurs se retrouvent d'un enregistrement source à l'autre (`1a77daf4d`).
- [ ] Mesure de sa précision sur des cas relus.
- [ ] Taille du groupe hors `dataset` et `software` : évaluer le signal.

### 4. Verdicts durables

- [x] Tables des fusions forcées, ancrées sur `(source, source_id)` (4523e022c).
- [ ] Jeton de fusion lu par la réconciliation : un bras du voisinage, une clé de confirmation.
- [ ] Réconciliation ciblée sur une liste d'enregistrements sources, hors de la file.
- [ ] Fusion forcée exposée par `pipeline/public.py` : jeton, réconciliation ciblée, métadonnées consolidées, réalignement des auteurs de la publication conservée, périmètre et compteurs. Les contributions de la publication absorbée gardent leur rattachement aux personnes.
- [ ] Volet : doublons potentiels par similarité de titre, champ « Fusionner » (identifiant, DOI ou titre).
- [ ] Interdiction de fusion, relue par la réconciliation.
- [ ] Ancrage de `persons.rejected_contributions` sur `(source, source_id)`.
- [ ] Veto de l'administration sur un lien entre contribution source et structure, relu par le calcul du périmètre. Action dans le volet.

## Questions ouvertes

- **Auteurs** : comment les présenter dans le volet ? La comparaison des sources de la page publique y a sa place, mais l'alignement par position devient illisible au-delà de quatre ou cinq sources.
- **Disposition du volet** : une colonne par enregistrement source et une ligne par champ, à l'essai. À partir de combien d'enregistrements sources la disposition inverse devient-elle plus lisible ? Largeur ?
- **Interdiction de fusion** : forme du verdict, et son effet sur deux enregistrements sources qui partagent un DOI.
