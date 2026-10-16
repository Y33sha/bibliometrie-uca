# Chantier — Pays des signatures : candidats et résolution

## Contexte

Le pays d'une adresse est déduit par plusieurs moyens de fiabilité inégale, et le résultat est rangé dans deux colonnes de `addresses` : `countries` pour ce qui fait autorité, `suggested_countries` pour ce qui attend une confirmation humaine.

Six moyens écrivent l'un ou l'autre :

| Moyen | Site | Colonne écrite |
|---|---|---|
| pays détectés par ScanR dans le texte de l'affiliation (`detected_countries`) | `pipeline/ingestion/scanr/normalize.py`, écrit par `pipeline/ingestion/common/signatures.py` | `countries` |
| pays de la structure désambiguïsée par OpenAlex | `pipeline/ingestion/openalex/normalize.py`, écrit par `pipeline/ingestion/common/signatures.py` | `suggested_countries` |
| nom de pays en fin d'adresse | `pipeline/transformation/structures/countries/detect_by_country_name.py` | `countries` |
| nom d'institution ou de ville, via `ref.place_name_forms` | `pipeline/transformation/structures/countries/detect_by_place_name.py` | `countries` |
| emprunt du pays d'une adresse qui contient celle-ci | `pipeline/transformation/structures/countries/suggest_countries.py` | `suggested_countries` |
| saisie à la main, recopiée sur les adresses de même `normalized_text` | `application/services/addresses/countries.py` | `countries` |

Les sources écrivent seulement sur une adresse sans pays : la première notice normalisée l'emporte. Les détections du pipeline traitent seulement les adresses sans pays. Une suggestion vide (`[]`) marque une adresse tentée sans résultat.

Couverture obtenue, sur 507 902 adresses de la base de test : 483 838 ont un pays faisant autorité (95,3 %), 19 154 n'ont qu'une suggestion (3,8 %), 4 910 n'ont rien (1,0 %). La base de test vaut la base de prod pour les adresses et les pays. Ce stock contient les noms de structures HAL et ScanR, qui quittent `addresses` à la reprise du stock du chantier `DATA_perimetre.md` : 20 660 adresses sont portées par les seules signatures HAL.

Le dispositif fonctionne. Ce sont les conséquences de la modélisation en deux colonnes qui motivent ce chantier.

**La confiance est encodée dans le schéma.** L'autorité d'une valeur se déduit de la colonne qui la contient. Chaque écriture doit donc maintenir « je n'écris la suggestion qu'en l'absence de pays », par une clause `WHERE` répétée à chaque site ; chaque lecture doit connaître la règle de promotion.

**Le moyen qui a produit une valeur n'est conservé nulle part.** Une fois `countries` écrit, rien ne dit si le pays vient de ScanR, d'un nom de pays en fin d'adresse ou d'une institution reconnue. La justesse de chaque moyen est donc invérifiable, et les arbitrages entre moyens reposent sur des jugements a priori.

**Le principal de ces jugements oppose OpenAlex à ScanR.** Le pays OpenAlex est écarté de l'autorité au motif qu'il est « algorithmique et faillible » ; le pays ScanR y est admis. Les deux proviennent pourtant d'une désambiguïsation faite par la source. Cette asymétrie n'a jamais été confrontée aux données.

**Les désaccords sont perdus.** Quand plusieurs lieux reconnus dans une adresse désignent des pays différents, la détection abandonne l'adresse sans conserver ce qu'elle a trouvé.

**Des signatures sont sans adresse.** Les signatures HAL, celles des fiches de structure ScanR et celles des thèses n'ont pas de texte d'affiliation. Leur pays vient seulement de leurs identifiants : ROR, structure HAL (`ref.hal_structures.country_code`). Dans la base de test, 1 923 publications du périmètre sur 69 293 tiennent tous leurs pays d'adresses HAL.

**Le ROR d'une signature est relié à son affiliation.** La normalisation rattache chaque ROR à l'adresse de son affiliation (`source_authorship_rors.address_id`) ; un ROR sans texte d'affiliation reste sur la signature. Sur 5 000 notices OpenAlex du raw store, 587 407 ROR sont reliés à un texte et 9 ne le sont pas. Un même texte peut porter plusieurs ROR. Le référentiel ROR donne le pays de chaque organisation (`ror_organizations.country_code`). OpenAlex donne parfois un ROR faux, dont le pays contredit l'adresse.

**Seule la publication porte un pays agrégé.** `source_publications.countries` et `publications.countries` réunissent les pays des adresses. Le tableau de cohérence des sources de la page publication dérive les pays de chaque signature de ses adresses.

## Décisions

**Deux niveaux.** Les moyens tirés du texte portent sur l'adresse : leur résultat vaut pour toutes les signatures de ce texte. Les moyens tirés d'un identifiant portent sur la signature : `ror`, `hal_structure`.

**Une table de candidats pour les adresses.** Un candidat est un pays proposé pour une adresse par un moyen donné.

```
address_country_candidates
  address_id    → addresses(id)
  country_code  → countries(code)
  method        énumération fermée
  score         nullable
  detected_at
  PRIMARY KEY (address_id, country_code, method)
```

Les moyens tirés du texte deviennent les valeurs de `method` : `source_scanr`, `source_openalex`, `country_name`, `institution`, `city`, `similarity`, `manual`. Une source n'a pas de statut particulier : elle est un moyen parmi les autres, mesurable comme les autres. La copie d'une saisie manuelle vers les adresses de même `normalized_text` est un candidat `manual`.

Une adresse à deux pays donne deux lignes. Un désaccord entre moyens donne deux lignes de `method` différentes, conservées au lieu d'être abandonnées.

**La préséance s'écrit à un seul endroit.** Une fonction du domaine lit les candidats d'une adresse et compose l'ensemble retenu. `manual` l'emporte sur tout. Le reste du classement est fixé par la mesure, non a priori.

**Pays d'une signature, affiliation par affiliation.** Une adresse donne son pays retenu, ou à défaut le pays des ROR de son affiliation. Un ROR sans adresse et une structure HAL donnent leur pays. Le pays de la signature réunit ces pays. La règle est conditionnée à la mesure des contradictions.

**Colonne `source_authorships.countries`.** Elle porte le pays de la signature, calculé par la seule règle ci-dessus. La cascade vers `source_publications` et la page publication la lisent. Elle est conditionnée à la même mesure.

**La mesure se fait hors pipeline.** Un script lit le stock entier et exécute chaque moyen sur chaque adresse, indépendamment des autres moyens. Les pays des sources viennent des payloads du raw store, lus directement : `staging` reste intact. Le script écrit les candidats dans des fichiers, et la base reste intacte. Il applique ensuite la fonction de préséance et compare son résultat à `addresses.countries`. Le pipeline ne réévalue jamais tout le stock : il traite les adresses nouvelles.

**Le câblage dépend du gain mesuré.** Tant que la mesure ne montre pas de gain, rien ne change dans le schéma ni dans le pipeline.

**Au câblage :**
- les candidats du stock viennent des fichiers du script, et aucune colonne existante n'est reprise. Le stock n'a donc pas de candidat `manual` : le consensus entre moyens corrige les erreurs de `addresses.countries` ;
- `addresses.countries` demeure, comme cache dénormalisé lu par le calcul du pays des signatures et par les facettes de l'interface, dérivé des candidats par la seule fonction de préséance ;
- `addresses.suggested_countries` disparaît : une suggestion est un candidat dont le moyen n'accède pas seul à l'ensemble retenu ;
- le marqueur « tentée sans résultat » (`[]`) disparaît avec elle.

## Phasage

### 1. Script de candidats, hors pipeline

- [x] Script en lecture seule : pour chaque adresse du stock, les candidats de chaque moyen, écrits dans un fichier (`interfaces/cli/oneshot/measure_address_country_candidates.py`, 56c33a438).
- [x] Moyens `country_name`, `institution`, `city` : détecteurs du pipeline réutilisés, `institution` et `city` séparés par la nature du lieu (`place_name_forms.kind`).
- [x] Moyen `similarity` : emprunt au pool des adresses à pays, jumelles exclues.
- [x] Moyens `source_scanr`, `source_openalex` : pays lus dans les payloads du raw store, rattachés aux adresses par leur texte.
- [x] Moyen `ror` : pays des organisations ROR de la signature, pour chaque adresse de la signature.
- [x] Volume, sur 508 057 adresses de la base de test : 1 576 622 candidats. Les sources donnent le pays de chaque affiliation (6c7dec11d).
- [ ] Passe du script sur le stock réhydraté, sans les noms de structures HAL et ScanR.

| Moyen | Candidats | Adresses couvertes |
|---|---|---|
| `country_name` | 401 908 | 79,1 % |
| `institution` | 362 450 | 70,0 % |
| `city` | 236 942 | 46,4 % |
| `source_openalex` | 280 539 | 54,2 % |
| `ror` | 130 161 | 18,4 % |
| `similarity` | 108 005 | 20,5 % |
| `source_scanr` | 56 617 | 11,1 % |

### 2. Mesure et fonction de préséance des adresses

- [x] Par moyen : taux d'accord, de désaccord et de silence avec les autres moyens et avec `addresses.countries` (`interfaces/cli/oneshot/measure_address_country_agreement.py`, bca44eba5).
- [ ] Revue à la main d'un échantillon de désaccords, qui sert de référence.
- [ ] Trancher l'asymétrie OpenAlex / ScanR, et le sort de `similarity`.
- [ ] Fonction de préséance du domaine, testée. Le script l'applique au stock.
- [ ] Bilan : adresses gagnées, perdues et changées par rapport à `addresses.countries`. Décision de câblage.

### 3. Pays des signatures

- [ ] Mesure par source, sur le stock réhydraté : pays d'une adresse contre pays des ROR de la même affiliation ; ROR d'une même adresse entre eux ; ROR sans adresse contre adresses de la même signature. Revue à la main d'un échantillon de chaque cas.
- [ ] Moyen `hal_structure` : couverture et accord avec les ROR de la signature.
- [ ] Bilan : publications gagnées, perdues et changées par rapport à `publications.countries`. Décision sur la règle et la colonne.

### 4. Câblage

- [ ] Migration : table `address_country_candidates`, énumération `country_detection_method`, index sur `address_id`.
- [ ] Chargement des candidats du stock depuis les fichiers du script.
- [ ] Chaque moyen du pipeline écrit son candidat pour les adresses nouvelles ; `pipeline/graph.py` déclare la table.
- [ ] Étape de résolution : la fonction de préséance écrit `addresses.countries` et pose `countries_dirty`. Les moyens cessent d'écrire `addresses.countries`.
- [ ] Migration : colonne `source_authorships.countries`. Étape signature dans la cascade vers les publications. Un changement de pays dans les référentiels ROR et HAL marque les signatures concernées. La page publication lit la colonne.

### 5. Édition manuelle et retrait de la seconde colonne

- [ ] La page d'administration des pays lit les candidats et leur moyen, au lieu de `suggested_countries`.
- [ ] Une décision humaine s'enregistre en candidat `manual`, laissant en place ce que les moyens automatiques ont trouvé.
- [ ] Migration : suppression de `addresses.suggested_countries` et des points d'entrée qui la servent.

## Questions ouvertes

- **Score.** La préséance entre moyens suffit-elle, ou faut-il une valeur numérique par candidat ? Un score a du sens seulement si un moyen produit des propositions de qualité inégale, ce que la mesure dira.
- **Désaccords.** Une adresse dont les moyens se contredisent demande une décision humaine. Reste à décider si elle rejoint la file existante ou la sienne.
- **ROR et OpenAlex.** Le pays de la structure OpenAlex dérive en général de son ROR. Les moyens `ror` et `source_openalex` sont-ils redondants pour les signatures OpenAlex ?
- **Adresses dédoublonnées.** Stocker une adresse par `normalized_text` retirerait 72 946 lignes sur 507 902 (14,4 %) dans la base de test. Pour 1 262 textes normalisés, les lignes ont des pays différents.
- **Villes.** `place_name_forms` compte 192 villes, cherchées dans tout le texte de l'adresse. Piste : les villes de GeoNames (`cities15000`, licence CC BY 4.0), sans les noms portés par des villes de plusieurs pays (Cambridge, Valencia), et sans ceux qui sont déjà une forme de pays ou d'institution. Mesure avant chargement, contre les verdicts de la revue à la main.
- **Formes d'institutions.** `place_name_forms` compte 36 361 institutions. Le ROR et le référentiel HAL donnent le pays des organisations. Une partie des formes est bruitée : adresses complètes, parfois multiples, pays erronés (« goma volcano observatory » rangé en `cg`). Piste : retirer les institutions, après mesure de ce que le moyen `institution` apporte en plus du ROR et des structures HAL.
- **Tutelles ScanR écartées.** Leurs ROR restent sur la signature sans adresse. Elles ont en général le pays du laboratoire ; la mesure des ROR sans adresse le vérifie.
