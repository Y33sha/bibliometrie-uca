# Chantier — Pays des adresses : candidats et résolution

## Contexte

Le pays d'une adresse est déduit par plusieurs moyens de fiabilité inégale, et le résultat est rangé dans deux colonnes de `addresses` : `countries` pour ce qui fait autorité, `suggested_countries` pour ce qui attend une confirmation humaine.

Cinq endroits écrivent l'un ou l'autre :

| Site | Moyen | Colonne écrite |
|---|---|---|
| `application/pipeline/normalize/normalize_scanr.py` | pays déclaré par ScanR | `countries` |
| `application/pipeline/normalize/normalize_openalex.py` | pays de la structure désambiguïsée par OpenAlex | `suggested_countries` |
| `application/pipeline/countries/detect_by_country_name.py` | nom de pays en fin d'adresse | `countries` |
| `application/pipeline/countries/detect_by_place_name.py` | nom d'institution ou de ville, via `place_name_forms` | `countries` |
| `application/pipeline/countries/suggest_countries.py` | emprunt du pays d'une adresse qui contient celle-ci | `suggested_countries` |
| `application/services/addresses/countries.py` | saisie par la curation | `countries` |

Couverture obtenue, sur 431 912 adresses : 415 397 ont un pays faisant autorité (96,2 %), 12 986 n'ont qu'une suggestion (3,0 %), 3 529 n'ont rien (0,8 %).

Le dispositif fonctionne. Ce sont les conséquences de la modélisation en deux colonnes qui motivent ce chantier.

**La confiance est encodée dans le schéma.** L'autorité d'une valeur se déduit de la colonne qui la porte. Chaque écriture doit donc maintenir « je n'écris la suggestion qu'en l'absence de pays », par une clause `WHERE` répétée à chaque site ; chaque lecture doit connaître la règle de promotion.

**Le moyen qui a produit une valeur n'est conservé nulle part.** Une fois `countries` écrit, rien ne dit si le pays vient de ScanR, d'un nom de pays en fin d'adresse ou d'une institution reconnue. La justesse de chaque moyen est donc invérifiable, et les arbitrages entre moyens reposent sur des jugements a priori.

**Le principal de ces jugements oppose OpenAlex à ScanR.** Le pays OpenAlex est écarté de l'autorité au motif qu'il est « algorithmique et faillible » ; le pays ScanR y est admis. Les deux proviennent pourtant d'une désambiguïsation faite par la source. Cette asymétrie n'a jamais été confrontée aux données.

**Les désaccords sont perdus.** Quand plusieurs lieux reconnus dans une adresse désignent des pays différents, la détection abandonne l'adresse sans conserver ce qu'elle a trouvé.

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

Les moyens deviennent les valeurs de `method` : `source_scanr`, `source_openalex`, `country_name`, `institution`, `city`, `similarity`, `manual`. Une source n'a pas de statut particulier — elle est un moyen parmi les autres, mesurable comme les autres.

Le tableau des colonnes `countries` reçoit sa contrepartie naturelle : une adresse à deux pays donne deux lignes. Un désaccord entre moyens donne deux lignes de `method` différentes, conservées au lieu d'être abandonnées.

**La préséance s'écrit à un seul endroit.** Une étape de résolution lit les candidats d'une adresse et compose l'ensemble retenu : `manual` l'emporte sur tout ; les moyens tenus pour sûrs composent l'ensemble quand ils s'accordent ; `similarity` n'accède jamais seule à l'ensemble retenu et reste offerte à la curation. Le classement précis des moyens est fixé par la mesure de la phase 3, non a priori.

**`addresses.countries` demeure**, comme cache dénormalisé lu par la cascade vers les publications et par les facettes de l'interface. Il change de statut : dérivé des candidats par la seule étape de résolution, au lieu d'être écrit par six sites.

**`addresses.suggested_countries` disparaît.** Une suggestion est un candidat dont le moyen n'accède pas seul à l'ensemble retenu.

## Phasage

### 1. Table de candidats et reprise de l'existant

- [ ] Migration : table `address_country_candidates`, énumération `country_detection_method`, index sur `address_id`.
- [ ] Reprise des deux colonnes existantes : `countries` en `method = 'legacy'`, `suggested_countries` en `method = 'similarity'`.
- [ ] Aucun changement de comportement : rien ne lit encore la table.

### 2. Chaque moyen écrit son candidat

- [ ] Les six sites d'écriture ajoutent leur candidat, en conservant l'écriture actuelle des deux colonnes.
- [ ] `detect_by_place_name` enregistre aussi les désaccords, au lieu d'abandonner l'adresse.
- [ ] Toujours aucun changement de comportement : les colonnes restent la source de vérité.

### 3. Mesure de la justesse de chaque moyen

- [ ] Confronter chaque `method` à l'ensemble retenu, adresse par adresse : taux d'accord, de désaccord, de silence.
- [ ] Trancher l'asymétrie OpenAlex / ScanR sur cette mesure.
- [ ] Décider du sort de `similarity` : son taux d'accord détermine si elle est conservée, promue ou retirée.
- [ ] Arrêter le classement de préséance en conséquence.

### 4. Résolution dérivée et bascule des écritures

- [ ] Écrire l'étape de résolution appliquant la préséance arrêtée en phase 3.
- [ ] Vérifier qu'elle reproduit `addresses.countries` à l'identique sur tout le stock, aux écarts près que la phase 3 justifie. Ce contrôle autorise la bascule.
- [ ] Les moyens cessent d'écrire `addresses.countries` ; la résolution en devient seule écrivaine et pose `countries_dirty`.

### 5. Curation et retrait de la seconde colonne

- [ ] La page d'administration des pays lit les candidats et leur moyen, au lieu de `suggested_countries`.
- [ ] Une décision humaine s'enregistre en candidat `manual`, laissant en place ce que les moyens automatiques ont trouvé.
- [ ] Migration : suppression de `addresses.suggested_countries` et des points d'entrée qui la servent.

## Questions ouvertes

- **Score.** La préséance entre moyens suffit-elle, ou faut-il une valeur numérique par candidat ? Un score n'a de sens que si un moyen produit des propositions de qualité inégale, ce que la phase 3 dira.
- **Désaccords.** Une fois conservés, où sont-ils présentés ? Une adresse dont les moyens se contredisent est un cas de curation, pas un rejet silencieux — reste à décider si elle rejoint la file existante ou la sienne.
- **Rétention.** Les candidats d'un moyen retiré sont-ils supprimés, ou conservés comme trace de ce qui a été essayé ?
- **Volume.** Le nombre de candidats par adresse conditionne la taille de la table ; à mesurer en phase 2 sur le stock réel.
