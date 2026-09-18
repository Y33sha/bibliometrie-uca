# Chantier — Revues divergentes selon les sources

## Contexte

Les enregistrements d'une même publication portent parfois des revues différentes selon leur source. Des échantillons examinés sur une base qui n'a reçu ni les fusions (phase 4) ni les règles sur les livres (phase 6) du chantier [Revues](DATA_revues-issn-et-doublons.md) montrent cinq causes :

- **Doublon de revues.** Hors ISSN et titre communs, ce sont surtout des abréviations de titre sans espace : `Phys.Rev.Lett.`, `Eur.Phys.J.C`, `JINST`. C'est la forme des titres dans INSPIRE, la base bibliographique de la physique des hautes énergies. HAL et ScanR les portent sans ISSN ni éditeur, sur des dépôts des laboratoires de l'IN2P3.
- **Livre ou chapitre.** La plateforme de l'éditeur (OpenAlex, ScanR) s'oppose au titre du livre (Crossref).
- **Titre de revue parasite.** Des copies d'articles sont déposées dans des entrepôts (DESY, GSI). Le normaliseur DataCite crée une revue à partir de leur titre de conteneur, volume compris : `Physical review / D D 99(1)`.
- **Revue erronée dans une source, ou niveau de collection différent.** *SSRN Electronic Journal* (ScanR) pour un article de *Journal of Development Economics*, *Microscopy Today* (HAL) pour un article de *Microscopy*.
- **Enregistrements réunis à tort dans une publication.** *Annals of Forest Science* et *Peer Community In Forest and Wood Sciences* (HAL, sans DOI).

Quand Crossref fournit une revue, la publication prend celle-là : Crossref passe avant toutes les autres sources qui en fournissent une.

## Phasage

### 1. Mesure

- [ ] Script d'audit versionné : classement des couples (publication, revue A, revue B) par cause, échantillons.
- [ ] Mesure en production.

### 2. Titres parasites

- [x] Origine : notices DataCite qui ne décrivent pas la version publiée. Ce sont surtout des copies d'articles déposées par les entrepôts GSI, DESY et RWTH, de type `Text` : DataCite découpe mal leur `SeriesInformation`, une citation en texte libre (« Physics letters / B 777 »). S'y ajoutent des notes de version de logiciels Zenodo et des mentions de pagination (« 22 Seiten (2023). »).
- [x] Normalisation DataCite : le conteneur désigne une revue seulement quand la notice décrit la version publiée (`describes_published_version`). Mesure sur la base locale : 67 publications perdent leur seule revue, dont une trentaine de titres parasites ; les actes LIPIcs et les revues de type `JournalArticle` gardent la leur.
- [ ] Stock : oneshot `backfill_detach_datacite_journals`, puis `publishers_journals` pour supprimer les revues vidées.
- [ ] Autres sources : mesure en production après le nettoyage de DataCite.

### 3. Doublons restants

- [x] Règle de fusion dans `publishers_journals` : revues que les enregistrements d'une même publication portent, sous des titres compatibles (`compatible_titles`), et qui n'ont pas chacune des ISSN sans aucun en commun. Simulation sur la base locale : 104 fusions, aucune à tort.
- [ ] Mots que l'abréviation omet (`Nucl.Instrum.Meth.A` pour *Nuclear Instruments and Methods in Physics Research Section A*) : hors de la règle, à examiner après la mesure en production.

### 4. Revue erronée dans une source

- [ ] Règle construite sur les cas réels : revue de Crossref, éditeur du préfixe DOI.

### 5. Enregistrements réunis à tort

- [ ] Examen des cas relevés.

## Questions ouvertes

- Revue erronée dans une source : aligner l'enregistrement sur la revue de Crossref, avec trace dans `raw_metadata`, ou le signaler dans l'administration ?
