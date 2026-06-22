# Chantier — Gestion et dédoublonnage assistés de la base personnes

Commencé le 2026-06-22

## Contexte

La base personnes a dépassé la taille gérable à la main. `admin/persons` est devenue ingérable :

- **~1,6k personnes avec notice RH** (`persons_rh`) : les enseignants-chercheurs UCA de l'année courante.
- **~15k autres**, légitimes ou parasites, sans moyen simple de les trier :
  - personnels d'établissements co-tutelles (CNRS, Inserm, INRAE) co-signant sous un labo UCA — **légitime** ;
  - quelques personnels non enseignants-chercheurs — **légitime** ;
  - enseignants-chercheurs partis (retraite, mutation) et anciens doctorants — **OK** ;
  - chercheurs hébergés temporairement par le passé (?), ayant co-signé quelques publications UCA ;
  - **erreurs de parsing** : signatures parfois bloquées ensemble, appliquées en bloc à tous les co-auteurs d'une publication ;
  - **doublons non corrigés**, à fusionner.

Ce volume est impossible à dédupliquer et corriger efficacement à la main. Il faut une **aide automatisée** : classification des cas, correction des erreurs nettes, et suggestions pour les cas qui restent du ressort humain.

Ce chantier prolonge [DATA_identifiants-partages-dubious](archived/2026-06-22_DATA_identifiants-partages-dubious.md), qui a traité la corruption **dense** (un identifiant recopié sur tous les co-auteurs d'un même enregistrement). Restent ici la corruption **éparse** (un identifiant mal placé, un porteur par publication) et, plus largement, l'outillage de gestion à l'échelle.

## Deux prongs : prévenir la contamination, puis outiller le dédoublonnage

Le problème a deux faces complémentaires : **empêcher de nouvelles erreurs d'identifiant source de polluer le pipeline**, et **aider à trier/corriger le stock existant**.

### Prévention — empêcher les identifiants source erronés de contaminer le matching

Plusieurs leviers complémentaires :

1. **Corroboration par le nom au matching par identifiant.** Un match par ORCID/idref/hal qui pointe une personne dont le nom est **incompatible** avec celui de la signature (`names_compatible`, `domain/names.py`) est rejeté. Couvre la corruption éparse (« adrien gosselin pali » avec l'ORCID d'« Azomahou ») que le garde par-publication ne voit pas. Risque à mesurer : faux positifs sur changement de nom / translittération.
2. **Restreindre le matching aux identifiants `confirmed`** (option de config). Les identifiants `pending` (ajoutés automatiquement par le pipeline, non vérifiés) restent **no-op** tant que non confirmés manuellement. Plus conservateur ; suppose un flux de confirmation et accepte plus d'orphelins en attendant.
3. **Vérification externe via l'API ORCID.** Un appel par identifiant (pas par signature) pour récupérer le nom canonique associé à l'ORCID — et, si exposés, l'affiliation et le suffixe de l'adresse mail. Confronté au nom de la personne ciblée, c'est un signal de **confirmation ou de rejet du couple identifiant ↔ personne** (pas du lien personne ↔ signature), qui alimente potentiellement le flux de confirmation. Pas une garantie absolue (certains profils ne renseignent que le nom ou le prénom, ou ont changé de nom — mariage, divorce), mais un signal de plus, d'autant plus fort si l'affiliation ou le domaine de l'adresse mail corrobore le périmètre UCA. À étendre éventuellement aux autres référentiels avec API (idref).

### Dédoublonnage assisté — deux sources de signal

1. **Formes de nom ambiguës** (≥2 personnes partageant une forme). Trois cas à distinguer algorithmiquement :
   - **a) ambiguïté légitime** : vrai homonyme (« Pierre Bonnet »), homonymie de patronyme avec initiale identique ;
   - **b) doublon** : les deux personnes sont en réalité la même → à fusionner ;
   - **c) erreur** : une forme a été rattachée par erreur à une personne, via un identifiant mal placé sur une authorship → à détacher/corriger.
   Imaginer des algorithmes de classification (a/b/c) pour aider la fusion et la correction.
2. **Conflits d'identifiants** : la phase persons peut produire des logs du type « impossible de rattacher l'identifiant x à la personne y : déjà attribué à z ». Ces conflits signent soit un **doublon réel**, soit une **erreur d'attribution** — à capturer et exploiter.

## Phases

### Phase 1 — Prévention

- [ ] **Corroboration par le nom au matching identifiant** : rejeter un match identifiant dont le nom est incompatible avec la personne ciblée. Mesurer d'abord l'ampleur (combien de matchs identifiant à nom incompatible) et le risque de faux positifs.
- [ ] **Config `confirmed`-only** : option restreignant le matching aux identifiants `confirmed` ; les `pending` deviennent no-op. Évaluer l'impact (volume d'orphelins, besoin d'un flux de confirmation).
- [ ] **Vérification ORCID via API** : un appel par identifiant ORCID (pas par signature) pour récupérer le nom canonique — et affiliation / domaine de l'adresse mail si exposés — et confirmer ou rejeter le couple **identifiant ↔ personne**. Mesurer la couverture (combien de profils renseignent un nom exploitable) et le taux de corroboration.

### Phase 2 — Signaux et classification

- [ ] **Classifieur des formes de nom ambiguës** (a/b/c) : définir les signaux discriminants et un score par cas.
- [ ] **Capture des conflits d'identifiants** : matérialiser les conflits (« id déjà attribué ») détectés par la phase persons dans une forme exploitable (table/vue), avec le type de conflit présumé (doublon vs erreur).

### Phase 3 — Outillage du dédoublonnage assisté

- [ ] Forme de l'outillage à trancher : **scripts de maintenance**, **phase dédiée du pipeline**, ou **assistance dans l'UI admin** (human-in-the-loop). Probablement un mélange : correction automatique des erreurs nettes (cas c à haute confiance), suggestions pour les doublons (cas b), et signalement des ambiguïtés légitimes (cas a) à laisser tranquilles.

### Phase 4 — Refonte UI `admin/persons`

- [ ] Toilettage de la page (vieillotte) : tri/filtrage par catégorie (RH / co-tutelle / parti / suspect), intégration des suggestions de fusion et des conflits, ergonomie de la déduplication de masse.

## Questions ouvertes

- **Signaux de classification a/b/c.** Quels discriminants entre homonyme légitime, doublon et erreur ? Pistes : publications partagées, identifiants partagés/compatibles, compatibilité fine des noms, recouvrement temporel des activités, co-auteurs et affiliations communes, présence/absence de notice RH. Un vrai homonyme a des réseaux de co-auteurs et des affiliations **disjoints** ; un doublon les a **communs**.
- **Catégorisation durable des personnes.** Faut-il matérialiser une typologie (RH / co-tutelle / ancien / hébergé / suspect) pour piloter l'affichage et le tri, ou la dériver à la volée ? Lien avec le périmètre (la personne reste, mais son statut vis-à-vis d'UCA évolue dans le temps).
- **Erreurs de parsing « signatures groupées »** (ex. publi 77832, « for the … study group ») : détection (une personne dont *toutes* les formes de nom proviennent d'une même publication ? une signature portant un nom manifestement collectif ?) et purge automatique.
- **Confirmed-only vs corroboration par le nom** : les deux options de prévention se cumulent-elles, ou l'une suffit-elle ? La corroboration par le nom est plus chirurgicale (ne bloque pas les `pending` légitimes) ; le confirmed-only est plus radical mais demande un flux de confirmation soutenable.
- **Flux de confirmation des identifiants** : si on s'appuie sur le statut `confirmed`, comment le confirmer à l'échelle (auto-confirmation sur faisceau d'indices ? confirmation humaine ciblée ?).
- **Frontière automatique / humain** : quels cas corriger d'office (erreurs nettes), quels cas seulement suggérer (doublons probables), quels cas ne jamais toucher (homonymes légitimes).
