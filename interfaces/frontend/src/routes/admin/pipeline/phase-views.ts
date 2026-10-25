/**
 * Présentation des indicateurs sur-mesure par phase.
 *
 * La couche données (`details` en base) reste neutre : clés techniques, chiffres, et valeurs métier (noms de Registration Agency, statuts OA…). Les libellés et la mise en forme vivent ici, ce qui les rend modifiables sans relancer le pipeline, rétroactivement sur les runs déjà enregistrés.
 *
 * Conventions d'affichage, combinables sur une même phase :
 * - `summary` : une liste verticale de métriques indépendantes (`details.summary`).
 * - `matrix` : un croisé qui arrange des chiffres plats de `details.summary` en lignes × colonnes (chaque cellule = `summary[`${row.key}_${col.key}`]`). Pur agencement de présentation : la donnée en base reste les chiffres plats.
 * - `tables` : un ou plusieurs tableaux, chacun alimenté par `details[source].rows` (chaque ligne porte une `key`, premier en-tête de colonne). Un tableau s'ajuste à son contenu plutôt que d'occuper toute la largeur.
 *
 * Une phase sans entrée ici retombe sur l'affichage générique des compteurs `PhaseMetrics` (total / new / updated / unchanged / errors / extras).
 */

export type SummaryItem = { key: string; label: string };
export type TableColumn = {
  key: string;
  label: string;
  pct?: boolean;
  // Valeur déjà exprimée en pourcentage (rendue « n % », pas de ligne de total).
  percent?: boolean;
  sign?: boolean;
  duration?: boolean;
};
export type TableView = {
  // Clé dans `details` portant `{ rows: [...] }`.
  source: string;
  // En-tête de la première colonne (les `key` des lignes). Vide pour une matrice dont les lignes sont elles-mêmes des en-têtes.
  firstColumnLabel: string;
  // Libellés d'affichage des `key` techniques des lignes. Clé absente → `key` brute. Garde la donnée en base neutre tout en présentant des intitulés lisibles.
  rowLabels?: Record<string, string>;
  columns: TableColumn[];
  total?: boolean;
};
export type MatrixView = {
  // Cellule = `summary[`${row.key}_${col.key}`]`.
  columns: { key: string; label: string }[];
  rows: { key: string; label: string }[];
};
export type PhaseView = {
  summary?: SummaryItem[];
  // Lignes de texte libres ; chaque `{clé}` est remplacé par `summary[clé]`. Pour les phases dont le résumé se lit mieux en phrases qu'en couples libellé/valeur.
  lines?: string[];
  matrix?: MatrixView;
  tables?: TableView[];
};

export const PHASE_VIEWS: Record<string, PhaseView> = {
  harvest: {
    tables: [
      {
        source: "table",
        firstColumnLabel: "Source",
        columns: [
          { key: "found", label: "Trouvés" },
          { key: "new", label: "Nouveaux" },
          { key: "updated", label: "Màj" },
          { key: "unchanged", label: "Inchangés" },
          { key: "duration_s", label: "Durée", duration: true },
        ],
        total: true,
      },
    ],
  },
  fetch_missing: {
    tables: [
      {
        source: "table",
        firstColumnLabel: "Canal",
        columns: [
          { key: "interrogated", label: "Interrogés" },
          { key: "new", label: "Nouveaux" },
          { key: "not_found", label: "Introuvables" },
          { key: "duration_s", label: "Durée", duration: true },
        ],
        total: true,
      },
    ],
  },
  fetch_stale: {
    tables: [
      {
        source: "table",
        firstColumnLabel: "Source",
        columns: [
          { key: "interrogated", label: "Interrogés" },
          { key: "refreshed", label: "Rafraîchis" },
          { key: "disappeared", label: "Disparus" },
          { key: "duration_s", label: "Durée", duration: true },
        ],
        total: true,
      },
    ],
  },
  normalize: {
    tables: [
      {
        source: "table",
        firstColumnLabel: "Source",
        columns: [
          { key: "processed", label: "Traités" },
          { key: "skipped", label: "Ignorés" },
          { key: "errors", label: "Erreurs" },
          { key: "duration_s", label: "Durée", duration: true },
        ],
        total: true,
      },
    ],
  },
  publishers_journals: {
    summary: [{ key: "doaj_matched", label: "DOAJ — journaux taggés" }],
    tables: [
      {
        source: "table",
        firstColumnLabel: "Sous-étape",
        columns: [
          { key: "traités", label: "Traités" },
          { key: "identifiés", label: "Identifiés" },
          { key: "créés", label: "Créés" },
        ],
      },
    ],
  },
  affiliations: {
    summary: [
      { key: "adresses", label: "Adresses traitées" },
      { key: "in_perimeter", label: "Adresses dans le périmètre" },
    ],
  },
  publications: {
    lines: [
      "{processed} source_records examinées, résolues en {publications} publications (dont {existing} déjà existantes)",
      "{created} nouvelles publications, dont {splits} par scission",
      "{merges} doublons fusionnés",
      "nouveau total : {publication_total} publications",
    ],
  },
  resolve_ra: {
    summary: [
      { key: "new_prefixes", label: "Nouveaux préfixes" },
      { key: "resolved", label: "Résolus" },
    ],
    tables: [
      {
        source: "table",
        firstColumnLabel: "Registration Agency",
        columns: [
          { key: "dois", label: "DOI", pct: true },
          { key: "prefixes", label: "Préfixes DOI", pct: true },
          { key: "new", label: "Run", sign: true },
        ],
        total: true,
      },
    ],
  },
  metadata_correction: {
    matrix: {
      columns: [
        { key: "examined", label: "source_records examinées" },
        { key: "corrected", label: "corrigées" },
      ],
      rows: [
        { key: "serial_by_doi", label: "Rattachement à la publication en série (par DOI)" },
        { key: "unary", label: "Corrections à l'unité" },
        { key: "cluster", label: "Corrections par grappe" },
      ],
    },
    tables: [
      {
        source: "table",
        firstColumnLabel: "Règle de correction",
        columns: [{ key: "count", label: "Nombre", pct: true }],
        total: true,
      },
    ],
  },
  relations: {
    tables: [
      {
        source: "table",
        firstColumnLabel: "Type de relation",
        columns: [{ key: "count", label: "Nombre", pct: true }],
        total: true,
      },
    ],
  },
  author_grouping: {
    summary: [
      { key: "publications", label: "Publications regroupées" },
      { key: "groups", label: "Groupes" },
      { key: "reference", label: "Contributions sources fondatrices d'un groupe" },
      { key: "name", label: "Liens par le nom" },
      { key: "identifier", label: "Liens par l'identifiant" },
      { key: "order", label: "Liens par l'ordre des homonymes" },
      { key: "model", label: "Liens par le modèle probabiliste" },
    ],
  },
  persons: {
    summary: [
      { key: "groups", label: "Contributions sans personne examinées" },
      { key: "written", label: "Contributions sans personne rattachées" },
      { key: "pinned", label: "Contributions rattachées par épinglage" },
      { key: "created", label: "Personnes créées" },
      { key: "create", label: "Contributions sans personne (nom inconnu, invalide)" },
      { key: "skip:ambiguous_name_form", label: "Contributions sans personne (nom ambigu)" },
      { key: "skip:all_candidates_rejected", label: "Contributions sans personne (candidats rejetés)" },
      { key: "skip:name_conflict", label: "Contributions sans personne (noms en conflit)" },
      { key: "skip:identifier_conflict", label: "Contributions sans personne (identifiants en conflit)" },
      { key: "skip:pin_conflict", label: "Contributions sans personne (épinglages en conflit)" },
      { key: "skip:person_in_other_group", label: "Contributions sans personne (personne déjà présente dans la publication)" },
      { key: "skip:creation_not_allowed", label: "Contributions sans personne (rôles de jury seuls)" },
      { key: "skip:out_of_perimeter", label: "Contributions sans personne (hors périmètre)" },
      { key: "first_names_completed", label: "Prénoms complétés" },
      { key: "identifiers_neutralized", label: "Identifiants portés sous le nom d'une autre personne, neutralisés" },
      { key: "identifiers_transferred", label: "Identifiants transférés" },
      { key: "ambiguous_marked", label: "Contributions à redécider (nom devenu ambigu)" },
      { key: "deleted_attributions", label: "Attributions d'identifiant supprimées" },
      { key: "deleted_persons", label: "Personnes supprimées" },
      { key: "name_forms_inserted", label: "Formes de nom ajoutées" },
      { key: "name_forms_updated", label: "Formes de nom modifiées" },
      { key: "name_forms_deleted", label: "Formes de nom supprimées" },
    ],
    tables: [
      {
        source: "table",
        firstColumnLabel: "Mode de rattachement",
        rowLabels: {
          manual: "Épinglage",
          orcid: "ORCID",
          hal_person_id: "Compte HAL",
          idref: "IdRef",
          name: "Nom sans homonymie",
          compatible_name: "Initiales compatibles",
          created: "Personne créée",
        },
        columns: [{ key: "count", label: "Contributions rattachées", pct: true }],
        total: true,
      },
    ],
  },
  finalize: {
    summary: [
      { key: "publications_purged", label: "Publications orphelines supprimées" },
      { key: "total_in_perimeter", label: "Contributions du périmètre" },
    ],
  },
  countries: {
    lines: [
      "{total} adresses",
      "{without_initial} sans pays ({without_pct} %)",
      "{newly_attached} pays nouvellement rattachés",
      "Reste {remaining} sans pays",
    ],
  },
  subjects: {
    lines: [
      "{subjects_added} sujets ajoutés (nouveau total : {subjects_total})",
      "{publications_updated} publications mises à jour",
    ],
  },
  oa_status: {
    summary: [
      { key: "stale", label: "DOI à vérifier" },
      { key: "checked", label: "Vérifiés" },
      { key: "new", label: "Nouveaux" },
      { key: "updated", label: "Modifiés" },
      { key: "unchanged", label: "Inchangés" },
      { key: "not_found", label: "Non trouvés" },
    ],
    tables: [
      {
        source: "table",
        firstColumnLabel: "Statut OA",
        columns: [
          { key: "count", label: "Nombre", pct: true },
          { key: "delta", label: "Δ", sign: true },
        ],
        total: true,
      },
    ],
  },
};
