# Chantier — Pays des adresses : candidats et résolution

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

Couverture obtenue, sur 507 902 adresses de la base de test : 483 838 ont un pays faisant autorité (95,3 %), 19 154 n'ont qu'une suggestion (3,8 %), 4 910 n'ont rien (1,0 %). La base de test vaut la base de prod pour les adresses et les pays.

Le dispositif fonctionne. Ce sont les conséquences de la modélisation en deux colonnes qui motivent ce chantier.

**La confiance est encodée dans le schéma.** L'autorité d'une valeur se déduit de la colonne qui la contient. Chaque écriture doit donc maintenir « je n'écris la suggestion qu'en l'absence de pays », par une clause `WHERE` répétée à chaque site ; chaque lecture doit connaître la règle de promotion.

**Le moyen qui a produit une valeur n'est conservé nulle part.** Une fois `countries` écrit, rien ne dit si le pays vient de ScanR, d'un nom de pays en fin d'adresse ou d'une institution reconnue. La justesse de chaque moyen est donc invérifiable, et les arbitrages entre moyens reposent sur des jugements a priori.

**Le principal de ces jugements oppose OpenAlex à ScanR.** Le pays OpenAlex est écarté de l'autorité au motif qu'il est « algorithmique et faillible » ; le pays ScanR y est admis. Les deux proviennent pourtant d'une désambiguïsation faite par la source. Cette asymétrie n'a jamais été confrontée aux données.

**Les désaccords sont perdus.** Quand plusieurs lieux reconnus dans une adresse désignent des pays différents, la détection abandonne l'adresse sans conserver ce qu'elle a trouvé.

**Le ROR des signatures donne un pays.** La normalisation rattache aux signatures les organisations ROR fournies par les sources (`source_authorship_rors`). Le référentiel ROR donne le pays de chaque organisation (`ror_organizations.country_code`).

## Décisions

**Une table de candidats.** Un candidat est un pays proposé pour une adresse par un moyen donné.

```
address_country_candidates
  address_id    → addresses(id)
  country_code  → countries(code)
  method        énumération fermée
  score         nullable
  detected_at
  PRIMARY KEY (address_id, country_code, method)
```

Les moyens deviennent les valeurs de `method` : `source_scanr`, `source_openalex`, `ror`, `country_name`, `institution`, `city`, `similarity`, `manual`. Une source n'a pas de statut particulier : elle est un moyen parmi les autres, mesurable comme les autres. La copie d'une saisie manuelle vers les adresses de même `normalized_text` est un candidat `manual`.

Une adresse à deux pays donne deux lignes. Un désaccord entre moyens donne deux lignes de `method` différentes, conservées au lieu d'être abandonnées.

**La préséance s'écrit à un seul endroit.** Une fonction du domaine lit les candidats d'une adresse et compose l'ensemble retenu. `manual` l'emporte sur tout. Le reste du classement est fixé par la mesure, non a priori.

**La mesure se fait hors pipeline.** Un script lit le stock entier et exécute chaque moyen sur chaque adresse, indépendamment des autres moyens. Les pays des sources viennent des payloads du raw store, lus directement : `staging` reste intact. Le script écrit les candidats dans des fichiers, et la base reste intacte. Il applique ensuite la fonction de préséance et compare son résultat à `addresses.countries`. Le pipeline ne réévalue jamais tout le stock : il traite les adresses nouvelles.

**Le câblage dépend du gain mesuré.** Tant que la mesure ne montre pas de gain, rien ne change dans le schéma ni dans le pipeline.

**Au câblage :**
- les candidats du stock viennent des fichiers du script, et aucune colonne existante n'est reprise. Le stock n'a donc pas de candidat `manual` : le consensus entre moyens corrige les erreurs de `addresses.countries` ;
- `addresses.countries` demeure, comme cache dénormalisé lu par la cascade vers les publications et par les facettes de l'interface, dérivé des candidats par la seule fonction de préséance ;
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

| Moyen | Candidats | Adresses couvertes |
|---|---|---|
| `country_name` | 401 908 | 79,1 % |
| `institution` | 362 450 | 70,0 % |
| `city` | 236 942 | 46,4 % |
| `source_openalex` | 280 539 | 54,2 % |
| `ror` | 130 161 | 18,4 % |
| `similarity` | 108 005 | 20,5 % |
| `source_scanr` | 56 617 | 11,1 % |

### 2. Mesure et fonction de préséance

- [x] Par moyen : taux d'accord, de désaccord et de silence avec les autres moyens et avec `addresses.countries` (`interfaces/cli/oneshot/measure_address_country_agreement.py`, bca44eba5).
- [ ] Revue à la main d'un échantillon de désaccords, qui sert de référence.
- [ ] Trancher l'asymétrie OpenAlex / ScanR, et le sort de `similarity`.
- [ ] Fonction de préséance du domaine, testée. Le script l'applique au stock.
- [ ] Bilan : adresses gagnées, perdues et changées par rapport à `addresses.countries`. Décision de câblage.

### 3. Câblage

- [ ] Migration : table `address_country_candidates`, énumération `country_detection_method`, index sur `address_id`.
- [ ] Chargement des candidats du stock depuis les fichiers du script.
- [ ] Chaque moyen du pipeline écrit son candidat pour les adresses nouvelles ; `pipeline/graph.py` déclare la table.
- [ ] Étape de résolution : la fonction de préséance écrit `addresses.countries` et pose `countries_dirty`. Les moyens cessent d'écrire `addresses.countries`.

### 4. Édition manuelle et retrait de la seconde colonne

- [ ] La page d'administration des pays lit les candidats et leur moyen, au lieu de `suggested_countries`.
- [ ] Une décision humaine s'enregistre en candidat `manual`, laissant en place ce que les moyens automatiques ont trouvé.
- [ ] Migration : suppression de `addresses.suggested_countries` et des points d'entrée qui la servent.

## Questions ouvertes

- **Score.** La préséance entre moyens suffit-elle, ou faut-il une valeur numérique par candidat ? Un score a du sens seulement si un moyen produit des propositions de qualité inégale, ce que la mesure dira.
- **Désaccords.** Une adresse dont les moyens se contredisent demande une décision humaine. Reste à décider si elle rejoint la file existante ou la sienne.
- **ROR et adresses.** Le ROR est rattaché à la signature, le pays à l'adresse. Pour une signature à plusieurs adresses et plusieurs ROR de pays différents, quelle adresse reçoit quel pays ?
- **ROR et OpenAlex.** Le pays de la structure OpenAlex dérive en général de son ROR. Les moyens `ror` et `source_openalex` sont-ils redondants pour les signatures OpenAlex ?
- **Adresses dédoublonnées.** Stocker une adresse par `normalized_text` retirerait 72 946 lignes sur 507 902 (14,4 %) dans la base de test. Pour 1 262 textes normalisés, les lignes ont des pays différents.
- **ROR par affiliation.** `source_authorship_rors` rattache les ROR à la signature : leur pays se pose sur toutes les adresses de la signature, d'où 15,6 % de sur-ensembles. OpenAlex et ScanR donnent le ROR de chaque affiliation. Faut-il rattacher le ROR au lien entre signature et adresse ?
- **Adresses qui ne sont pas des textes d'affiliation.** Les noms de structures HAL et ScanR et les adresses des thèses relèvent du chantier `DATA_perimetre.md`.
