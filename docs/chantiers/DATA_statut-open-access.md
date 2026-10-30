# Chantier — Statut open access tiré des copies

## Contexte

Le statut open access d'une publication combine le statut déclaré par chaque source et le verdict d'Unpaywall sur son DOI (`publication_oa_status`, `domain/publications/metadata.py`). Sans verdict, le statut le plus ouvert des sources l'emporte. Le statut déclaré par une source est invérifiable : il ne renvoie à aucune copie.

Une copie (`source_record_locations`) a seulement un booléen `is_oa`. La normalisation HAL convertit un embargo actif en `is_oa = false`, et la date de fin d'embargo reste sur l'enregistrement source (`source_records.embargo_until`). À l'échéance, une règle de correction fait passer le statut `embargoed` à `green`, mais la copie reste fermée. Le lien texte intégral, choisi parmi les copies ouvertes, ignore alors le fichier HAL.

### Mesures du 2026-10-30

Simulation sur les 76 591 publications du périmètre (`interfaces/cli/oneshot/measure_oa_floor.py`). Le plancher d'une publication vient de sa meilleure copie ouverte, et le verdict d'Unpaywall le relève. Une copie d'archive donne `green`. Une autre copie ouverte compte côté éditeur : une revue `full_oa` donne `gold`, ou `diamond` si le DOAJ indique ni APC ni autres frais ; une revue `subscription` donne `hybrid` avec une licence ouverte, `bronze` sans.

94,9 % des publications gardent leur statut. Écarts :

| Passage | Publications | Cause |
|---|---|---|
| `diamond` conservé | 3 404 sur 3 409 | le DOAJ des revues suffit |
| `green` → `bronze` | 2 710 | copies d'archive absentes du registre des plateformes, comptées côté éditeur |
| `closed` → ouvert | 346 | copies dites ouvertes par ScanR ou OpenAlex, verdict Unpaywall fermé |
| `embargoed` → `closed` | 116 | embargo absent des copies |
| ouvert → `closed` | environ 100 | statut ouvert déclaré par une seule source, sans copie ni verdict |

**Archives absentes du registre.** theses.fr (1 089 copies), `hdl.handle.net`, archives institutionnelles, serveurs de preprints derrière `doi.org` (bioRxiv, `10.1101`). OpenEdition, Cairn et Persée sont côté éditeur.

**Copies ouvertes douteuses.** 186 copies ScanR sur `doi.org` sont dites ouvertes, contre le verdict d'Unpaywall. 80 copies HAL sont dites ouvertes par ScanR ou OpenAlex, alors que l'enregistrement HAL les dit fermées. Les copies Persée sont réellement ouvertes.

**Absence de verdict.** 29 385 publications n'ont pas de DOI, et 5 061 DOI n'ont pas de verdict Unpaywall.

## Décisions

- Le statut d'une publication est le plancher tiré de sa meilleure copie ouverte, relevé par le verdict d'Unpaywall, jamais abaissé.
- Copie d'archive ou de serveur de preprints ouverte : `green`. Copie ouverte côté éditeur : le modèle de la revue décide, comme dans la simulation.
- `diamond` : revue au DOAJ sans APC ni autres frais. Un `gold` d'Unpaywall devient `diamond` aux mêmes conditions.
- La date de fin d'embargo est une colonne de la copie. L'ouverture d'une copie se calcule à la lecture : `is_oa` et embargo absent ou échu. Une copie sous embargo actif donne `embargoed`.
- L'embargo déclaré par theses.fr, sans copie ni date, reste un statut `embargoed`.
- Sans copie ouverte ni verdict : `closed`, ou `unknown` sans aucune information.

## Phasage

### Phase 1 — Copies fiables

- [x] Registre des plateformes : theses.fr, `hdl.handle.net`, archives institutionnelles, serveurs de preprints reconnus par préfixe DOI. Fiches du DOAJ, du DOAB et de PubMed écartées des copies. Reste `green` → `bronze` : 789 publications, à copie sur une plateforme d'éditeurs (OpenEdition, Cairn) ou à lien `doi.org` de ScanR. 2d9d97af7
- [x] La description d'une copie par sa propre plateforme prime : une copie HAL suit l'enregistrement HAL. `green` → `closed` : 1 019 publications. Parmi elles, 270 enregistrements sources HAL sans fichier, 224 dépôts HAL sans fichier principal, environ 300 publications dont la seule copie ouverte était une page du DOAJ, de PubMed ou une liste de Glasgow. ef34b5ae0
- [x] `is_oa` de ScanR sur les liens `doi.org` : mesurer contre Unpaywall, l'écarter s'il est peu fiable. Copies ouvertes à DOI vérifié par Unpaywall, hors DOI d'archive : verdict `closed` ou `green` pour 5,6 % des copies ScanR, 4,6 % des copies OpenAlex. ScanR est aussi fiable qu'OpenAlex.

### Phase 2 — Embargo sur les copies

- [x] Colonne `embargo_until` sur `source_record_locations`, retirée de `source_records`. La migration reporte la date sur les copies HAL et remet leur `is_oa` à vrai. 711dbf64a
- [x] Ouverture d'une copie calculée à la lecture (lien texte intégral, statut). La règle de correction lit la date sur la copie. 711dbf64a

### Phase 3 — Statut tiré des copies

- [ ] Consolidation du statut : plancher des copies, verdict d'Unpaywall, `diamond` par le DOAJ.
- [ ] Remesure avec `measure_oa_floor`, revue des écarts restants. Cas à vérifier :
  - publication 9705 : ouverte « via l'éditeur » pour un DOI Zenodo, avec une autre copie Zenodo ;
  - publication 78490 : fermée, alors que le DOI mène au PDF. Le DOI est enregistré chez KISTI, agence mal couverte par Unpaywall.

### Phase 4 — Documentation

- [ ] Mise à jour de la doc : statut open access dans `docs/pipeline/`, `docs/donnees/` et `docs/sources/`.

## Questions ouvertes

- Le statut déclaré par chaque source (`source_records.oa_status`) sert-il encore, hors embargo de theses.fr ?
- Dépôt HAL sans fichier principal, dit ouvert par HAL (`openAccess_bool`, annexe seule) : copie ouverte ou fermée ? La normalisation HAL la tient pour fermée. 224 publications.
- Copie ouverte sur `doi.org`, à DOI vérifié par Unpaywall : le verdict décide-t-il de son ouverture ? Unpaywall décrit la page de l'éditeur, comme HAL décrit ses dépôts. Le plancher compte sinon environ 5 % de copies faussement ouvertes.
