# Chantier — Gestion et dédoublonnage assistés de la base personnes

Commencé le 2026-06-22

## Contexte

La base personnes a dépassé la taille gérable à la main : `admin/persons` est devenue ingérable. Elle contient ~1,6k personnes avec notice RH (`persons_rh`, les enseignants-chercheurs UCA de l'année courante) et ~15k autres, mêlant des entrées légitimes et des parasites sans moyen simple de les trier :

- personnels d'établissements co-tutelles (CNRS, Inserm, INRAE) co-signant sous un labo UCA — légitime ;
- quelques personnels non enseignants-chercheurs — légitime ;
- enseignants-chercheurs partis (retraite, mutation) et anciens doctorants — légitime ;
- chercheurs hébergés temporairement par le passé, ayant co-signé quelques publications UCA ;
- erreurs de parsing : signatures parfois bloquées ensemble, appliquées en bloc à tous les co-auteurs d'une publication ;
- doublons non corrigés, à fusionner.

Ce volume est impossible à dédupliquer et corriger efficacement à la main. Il faut une aide automatisée : prévention des nouvelles contaminations, correction des erreurs nettes, et suggestions outillées pour les cas qui restent du ressort humain.

Ce chantier prolonge [DATA_identifiants-partages-dubious](archived/2026-06-22_DATA_identifiants-partages-dubious.md), qui a traité la corruption **dense** (un identifiant recopié sur toutes les positions d'auteur d'un même enregistrement source, neutralisé au normalize par le suffixe `_dubious`). Restent ici la corruption **éparse** (un identifiant mal placé, un seul porteur par publication, réparti sur des publications distinctes) et, plus largement, l'outillage de gestion et de dédoublonnage à l'échelle.

## Deux faces : prévenir la contamination, outiller le dédoublonnage

### Prévention — empêcher les identifiants source erronés de contaminer le matching

Trois leviers, librement re-priorisables selon praticité et impact mesuré :

1. **Corroboration par le nom au matching par identifiant.** Un match par ORCID / idref / hal qui pointe une personne dont le nom est incompatible avec la signature est rejeté. Couvre la corruption éparse (« adrien gosselin pali » portant l'ORCID d'« Azomahou ») que le garde par-publication ne voit pas. Levier le plus chirurgical et le moins coûteux (domaine pur, aucune I/O). Deux points d'implémentation établis par l'audit : (a) `decide_match_by_identifier` ne reçoit aujourd'hui que `{id_value: person_id}` — il faut enrichir les maps prefetchées avec le nom de la personne cible ; (b) la comparaison doit se faire **par ensemble de tokens** (à la manière de `_tokens_match` de l'admin, indépendant de l'ordre et tolérant aux initiales), pas par `names_compatible` positionnel : ce dernier rejette à tort « P.M. Llorca » contre « Pierre-Michel Llorca » et les noms de famille multi-mots tronqués par le parser (« Moutou Pitti » réduit à « Pitti »). L'abstention sur signature sans prénom reste utile mais marginale (une poignée de cas dans l'audit) ; le déterminant réel de la précision est la comparaison par tokens.
2. **Restreindre le matching aux identifiants `confirmed`** — option de configuration, `false` par défaut. Les identifiants `pending` (ajoutés automatiquement par le pipeline, non vérifiés) restent no-op tant que non confirmés. Sur une base vide sans identifiants curés, c'est un changement de comportement trop radical (les personnes découvertes par le pipeline n'ont que des `pending` et deviennent non-matchables par identifiant) ; sur une base déjà fournie et curée à la main, c'est une option conservatrice raisonnable. D'où le défaut `false` et l'activation décidée par l'utilisatrice.
3. **Vérification externe via l'API ORCID** — levier potentiellement en phase finale. Un appel par identifiant (pas par signature) récupère le nom canonique associé à l'ORCID — et, si exposés, l'affiliation et le suffixe de l'adresse mail. Confronté au nom de la personne ciblée, c'est un signal de confirmation ou de rejet du couple **identifiant ↔ personne** (pas du lien personne ↔ signature), qui alimente potentiellement le flux de confirmation du levier 2. Pas une garantie absolue (certains profils ne renseignent que le nom ou le prénom, ou ont changé de nom), mais un signal de plus, renforcé si l'affiliation ou le domaine de l'adresse mail corrobore le périmètre UCA. Extensible aux autres référentiels à API (idref).

### Dédoublonnage assisté — deux machineries distinctes

La classification a/b/c de la fiche d'origine se résout en **deux mécaniques de natures différentes** :

- **Signaux de paire** (deux personnes à comparer) → **fusion** quand c'est un doublon (b), **laisser tranquille** quand c'est un homonyme légitime (a). Sources de paires candidates : formes de nom partagées / compatibles (le générateur de paires actuel), et **même valeur d'identifiant brut portée par des `source_authorships` à `person_id` distincts** (souvent doublon, parfois erreur). Le tri a/b s'appuie sur des recouvrements chiffrés : co-auteurs, labos, sujets, revues — disjoints pointent vers l'homonyme légitime (a), communs vers le doublon (b).
- **Signaux mono-personne** (une seule personne, mal accrochée) → **détachement** (c). Deux détecteurs : (1) **même `person_id` sur ≥2 `source_authorships` d'une même `source_publication`** — une personne ne peut pas signer deux positions d'un même enregistrement, c'est une erreur certaine ; complémentaire du garde `_dubious` car cette double-accroche peut provenir d'un match par forme de nom, que `_dubious` ne voit pas ; (2) **nom manifestement collectif** sur la signature (« for the … study group », « consortium », « collaboration »). Variante de très haute précision du détecteur (1), mesurée par l'audit : quand sur une même `source_publication` une personne apparaît **deux fois** — une occurrence par identifiant au nom **incompatible** (l'intrus), une occurrence par nom **compatible** (le porteur légitime) — l'intrus est une erreur d'attribution d'identifiant prouvée, détachable d'office. L'audit en dénombre ~11,9k rattachements sur 104 personnes, à 99 % via ORCID crossref + openalex (réparti ~50/50, OpenAlex recopiant le `raw_orcid` de crossref ; HAL quasi propre, ORCID de provenance indépendante).

S'y ajoute la **capture des conflits d'identifiants** internes à la cascade de matching : quand les signaux identifiants d'une même authorship divergent (l'ORCID pointe la personne A, l'idref la personne B), ou qu'un identifiant brut pointe une personne différente de celle finalement retenue, la divergence signe un doublon réel ou une erreur d'attribution. Aujourd'hui la cascade tranche silencieusement par priorité (ORCID > hal > idref) ; matérialiser ces divergences en fait un signal exploitable.

## Phasage

Les phases sont librement re-shufflables selon praticité et pertinence mesurée.

### Phase 1 — Prévention

- [ ] **Corroboration par le nom au matching identifiant** : rejeter un match identifiant dont le nom est incompatible avec la personne ciblée, par **comparaison par tokens** (pas `names_compatible` positionnel). Ampleur mesurée par l'audit `interfaces/cli/oneshot/audit_identifier_name_corroboration.py` ; reste à statuer sur les faux rejets résiduels (changement de nom, translittération).
- [ ] **Verdict bloquant `name_form ↔ person`** (antidote à l'amplificateur secondaire — une signature mal rattachée devient une forme de nom de la personne et en attire d'autres par matching de nom) : un lien `(name_form, person_id)` `pending` par défaut, confirmable ou rejetable ; un rejet bloque toute attribution par nom de cette forme à cette personne, indépendamment des identifiants, et garantit le non-retour. Viable directement sur `person_name_forms` : statut sur la table, DELETE de synchronisation gardé sur `status = 'pending'` (préserve les verdicts au rebuild), lecture de matching filtrée sur les non-`rejected`. Pas de table dédiée requise.
- [ ] **Option de config `confirmed`-only** (défaut `false`) : restreint le matching aux identifiants `confirmed` ; les `pending` deviennent no-op. Évaluer l'impact (volume d'orphelins, besoin d'un flux de confirmation) avant d'envisager de l'activer sur une base curée.

### Phase 2 — Signaux et classification

- [ ] **Détecteurs de détachement (c)** : même `person_id` sur ≥2 `source_authorships` d'une même `source_publication` ; sa variante haute précision intrus-identifiant + porteur-légitime (~11,9k rattachements / 104 personnes, détachables d'office) ; nom manifestement collectif sur la signature.
- [ ] **Signaux de paire (a/b)** : valeur d'identifiant brut partagée entre `person_id` distincts ; recouvrements chiffrés (co-auteurs, labos, sujets, revues) pour trancher homonyme légitime (disjoints) vs doublon (communs). Définir l'agrégation en score.
- [ ] **Capture des conflits d'identifiants** : matérialiser (table/vue) les divergences de signaux identifiants détectées par la cascade de la phase persons, avec le type de conflit présumé (doublon vs erreur d'attribution).

### Phase 3 — Outillage du dédoublonnage assisté

- [ ] Forme à trancher : scripts de maintenance, phase dédiée du pipeline, ou assistance human-in-the-loop dans l'UI admin. Probablement un mélange : correction automatique des erreurs nettes (cas c à haute confiance), suggestions pour les doublons (cas b), signalement non-intrusif des homonymes légitimes (cas a) à laisser tranquilles.

### Phase 4 — UI `admin/persons` et dédoublonnage

L'existant ne donne pas satisfaction : le générateur de paires candidates impose une navigation forcée d'une paire à l'autre, n'expose comme éléments de décision que les titres des publications, et `distinct_persons` ne sert qu'à ne plus re-suggérer une paire. Deux options ouvertes, à trancher :

- [ ] **Remplacer** par un autre outil ;
- [ ] **Retravailler** l'existant pour le rendre utilisable : consultation de la **liste** des candidats doublons (au lieu de la navigation paire-par-paire imposée), et présentation des **éléments de décision chiffrés** (scores de recouvrement co-auteurs, sujets, revues, labos — pas seulement les titres de publications).

### Phase 5 — Automatisation de la vérification d'identifiants
- [ ] **Vérification ORCID via API** (levier flottant, possible en phase finale) : récupérer le nom canonique — et affiliation / domaine de l'adresse mail si exposés — et confirmer ou rejeter le couple identifiant ↔ personne. Mesurer la couverture (combien de profils exposent un nom exploitable) et le taux de corroboration.
- [ ] **API IdRef**?

## Questions ouvertes

- **Agrégation des recouvrements en score.** Pondération et seuils pour combiner co-auteurs / labos / sujets / revues en un score a vs b par paire. Un vrai homonyme a des réseaux disjoints ; un doublon les a communs — reste à calibrer la frontière.
- **Frontière automatique / humain.** Quels cas corriger d'office (erreurs nettes, cas c à haute confiance), quels cas seulement suggérer (doublons probables, cas b), quels cas ne jamais toucher (homonymes légitimes, cas a).
- **Corroboration par le nom : faux rejets résiduels.** La comparaison par tokens règle les initiales et les noms multi-mots ; restent les **changements de nom** (« Van Lander » → « Maneval », mariage / jeune fille) et les translittérations, où la signature et la personne n'ont aucun token en commun. À décider : rejeter quand même, ou conditionner le rejet à l'absence de tout autre signal concordant.
- **Flux de confirmation des identifiants.** Si on active `confirmed`-only, comment confirmer à l'échelle : auto-confirmation sur faisceau d'indices, confirmation humaine ciblée, ou apport de la vérification ORCID.
- **Vérification ORCID : modalités.** Contact polite-pool propre à l'API ORCID (distinct de celui d'OpenAlex), rate-limiting et cache, et destination des verdicts (transition `pending` → `confirmed` / `rejected` sur `person_identifiers`, ou table dédiée).
