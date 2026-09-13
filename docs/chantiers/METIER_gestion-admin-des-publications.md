# Chantier — Gestion des publications dans l'administration

## Contexte

**Menu d'administration.** Le menu « Référentiels » donne accès aux structures, aux personnes, aux éditeurs et aux revues. Les publications n'y figurent pas. Une entrée séparée, « Dédoublonnage », mène à `admin/duplicates`.

**La page `admin/duplicates`** présente une à une des paires de publications candidates à la fusion. Une paire partage le même titre normalisé (au-delà d'une longueur minimale), sans deux DOI différents, sans que les deux publications portent chacune une notice HAL, OpenAlex ou WoS, et hors des paires déclarées distinctes. Deux actions : fusionner (`POST /api/publications/duplicates/merge`, service `merge_publications`) et déclarer distinctes (`POST /api/publications/duplicates/mark-distinct`, table `distinct_publications`). Pièces : la route (375 lignes), trois points d'entrée de l'API, la lecture `infrastructure/read_models/publications/duplicates.py` et son port `PublicationDuplicatesQueries`, le client `$lib/api/duplicates.ts`.

**Ces deux actions ne sont pas durables.** La phase `publications` regroupe à chaque passage les notices sources qui partagent une clé de confirmation, dans le voisinage des notices modifiées. Une publication à cheval sur deux groupes est scindée. Une fusion manuelle entre publications sans clé commune est donc défaite dès que le voisinage de l'une de leurs notices est recalculé. La table `distinct_publications` n'est pas lue par le pipeline.

**Le référentiel Personnes sert de modèle.** La page `admin/persons` porte des onglets : la liste, puis quatre files de triage avec leur compteur. Un clic ouvre un volet droit (`?person=<id>` dans l'URL), large de 480 pixels au plus. Les verdicts qui s'y prennent — formes de nom rejetées, signatures détachées, personnes déclarées distinctes — sont des entrées que le pipeline relit à chaque passage.

**La comparaison des sources** vit dans la page publique d'une publication (`publications/[id]/SourceComparison.svelte`, 501 lignes), réservée à l'administration connectée. Elle aligne les auteurs par position pour quatre sources codées en dur : HAL, OpenAlex, WoS, ScanR. La réponse de l'API (`PublicationDetailResponse`) porte une liste de signatures par source nommée (`hal_authorships`, `openalex_authorships`…) : Crossref et DataCite n'y figurent pas.

**Une conception antérieure existe.** La fiche archivée [dédoublonnage par paires gardées](archived/2026-06-26_DATA_dedup-pairwise-gated.md) esquisse des « contrôles admin » sur le modèle opt-out : le pipeline fusionne d'office, l'administration contrôle a posteriori.
- Détecteur de fusions suspectes : recouvrement d'auteurs faible ou nul, titre court ou générique, `container_title` divergent pour les chapitres, groupe anormalement gros.
- Verdicts ancrés sur les `source_publications`, jamais sur les `publications`, dont l'identifiant change à chaque réconciliation : un discriminant de scission (valeurs différentes ⇒ jamais dans le même groupe) et un jeton de fusion forcée (valeur commune ⇒ même groupe), branchés sur les mécanismes de regroupement existants.

La fiche [Preprints fusionnés avec leur article par substitution de DOI](DATA_fusions-preprints-par-doi.md) renvoie un cas de fusion erronée à « l'outil admin de dédoublonnage ».

## Décisions

- **Une page `admin/publications`**, dans le menu « Référentiels », affiche la liste des publications de la page publique (`PublicationsListView`), inchangée.
- **Un clic sur une publication ouvre un volet droit**, comme dans le référentiel Personnes, bien plus large : il sert à confronter toutes les métadonnées des sources.
- **Des onglets**, comme dans le référentiel Personnes, accueillent la détection automatisée des fusions suspectes.
- **La page `admin/duplicates` et son entrée de menu disparaissent.**

## Phasage

### 1. Page et liste

- [x] Route `admin/publications`, entrée « Publications » dans le menu « Référentiels » (a85c42ed).
- [x] Liste des publications (a85c42ed).
- [x] Emplacement des onglets, avec la liste pour premier onglet : composant `HubTabs`, partagé avec le référentiel Personnes (13b4ed89).
- [x] Suppression de `admin/duplicates`, de son entrée de menu, et de la lecture des paires candidates (point d'entrée, port, adaptateur, tests, doc) (a85c42ed).
- [x] Suppression de la fusion et de la distinction manuelles, sans effet durable : points d'entrée, client, services, erreur `DistinctDoiError`, table `distinct_publications` (b52fb3d6).

### 2. Volet

- [x] Volet droit ouvert par `?publication=<id>`, fermé par Échap et par le fond : composant `Drawer`, partagé avec le référentiel Personnes.
- [x] Métadonnées de chaque notice source, confrontées, une colonne par notice : identifiants, titre, type, année, revue et ISSN, éditeur, conteneur, volume, numéro, pages, langue, statut OA.
- [x] Lecture de l'API qui rend les notices sources d'une publication, toutes sources confondues, sans champ nommé par source.

### 3. Détection des fusions suspectes

- [ ] Premiers détecteurs, un onglet chacun, avec leur compteur.
- [ ] Mesure de leur précision sur des cas relus.

### 4. Verdicts durables

- [ ] Modèle de persistance des verdicts de scission et de fusion forcée, relu par la réconciliation.

## Questions ouvertes

- **Auteurs** : comment les présenter dans le volet ? La comparaison des sources de la page publique y a sa place, mais l'alignement par position devient illisible au-delà de quatre ou cinq sources.
- **Disposition du volet** : une colonne par notice et une ligne par champ, à l'essai. À partir de combien de notices la disposition inverse devient-elle plus lisible ? Largeur ?
- **Premiers détecteurs** : lesquels, parmi ceux de la conception antérieure ? Les paires de titres identiques de `admin/duplicates` en font-elles partie ?
- **Verdicts** : discriminant de scission et jeton de fusion forcée ancrés sur les notices sources, comme dans la conception antérieure ? Ce choix touche le schéma et la réconciliation.
