/**
 * Présentation des indicateurs sur-mesure par phase.
 *
 * La couche données (`details` en base) reste neutre : clés techniques, chiffres,
 * et valeurs métier (noms de Registration Agency, statuts OA…). Les libellés et la
 * mise en forme vivent ici, ce qui les rend modifiables sans relancer le pipeline
 * (et donc rétroactifs sur les anciens runs).
 *
 * Conventions d'affichage, combinables sur une même phase :
 * - `summary` : une liste verticale de métriques indépendantes (`details.summary`).
 * - `matrix` : un croisé qui arrange des chiffres plats de `details.summary` en
 *   lignes × colonnes (chaque cellule = `summary[`${row.key}_${col.key}`]`). Pur
 *   agencement de présentation : la donnée en base reste les chiffres plats.
 * - `tables` : un ou plusieurs tableaux, chacun alimenté par `details[source].rows`
 *   (chaque ligne porte une `key`, premier en-tête de colonne). Un tableau s'ajuste
 *   à son contenu plutôt que d'occuper toute la largeur.
 *
 * Une phase sans entrée ici retombe sur l'affichage générique (compteurs
 * `PhaseMetrics` + volumes avant/après des tables produites).
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
  // En-tête de la première colonne (les `key` des lignes). Vide pour une matrice
  // dont les lignes sont elles-mêmes des en-têtes.
  firstColumnLabel: string;
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
  matrix?: MatrixView;
  tables?: TableView[];
};

export const PHASE_VIEWS: Record<string, PhaseView> = {
  extract: {
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
  cross_imports: {
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
  refresh_stale: {
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
  affiliations: {
    summary: [
      { key: "adresses", label: "Adresses traitées" },
      { key: "in_perimeter", label: "Adresses dans le périmètre" },
    ],
    tables: [
      {
        source: "table",
        firstColumnLabel: "Source",
        columns: [
          { key: "total", label: "source_authorships" },
          { key: "in_perimeter", label: "Dans le périmètre" },
          { key: "pct", label: "%", percent: true },
        ],
        total: true,
      },
    ],
  },
  publications: {
    summary: [
      { key: "sp_in_perimeter", label: "source_publications (in-périmètre)" },
      { key: "publications", label: "Publications" },
      { key: "dedup_factor", label: "Facteur de dédup (SP/pub)" },
      { key: "processed", label: "SP traitées (ce run)" },
      { key: "created", label: "Publications créées" },
      { key: "splits", label: "dont par scission" },
      { key: "existing", label: "Existantes conservées" },
      { key: "merges", label: "Doublons fusionnés" },
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
        { key: "examined", label: "source_publications examinées" },
        { key: "corrected", label: "corrigées" },
      ],
      rows: [
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
  countries: {
    summary: [
      { key: "addresses_total", label: "Adresses (pub_count > 0)" },
      { key: "with_country_before", label: "Avec pays (avant)" },
      { key: "with_country_after", label: "Avec pays (après)" },
      { key: "with_suggestion", label: "Avec suggestion" },
      { key: "without_country", label: "Sans pays ni suggestion" },
    ],
  },
  oa_status: {
    summary: [
      { key: "stale", label: "Publications à vérifier" },
      { key: "checked", label: "Vérifiées (cap 10 000)" },
      { key: "updated", label: "Mises à jour" },
      { key: "unchanged", label: "Inchangées" },
      { key: "not_found", label: "Non trouvées" },
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
