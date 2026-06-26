/**
 * Présentation des indicateurs sur-mesure par phase.
 *
 * La couche données (`details` en base) reste neutre : clés techniques, chiffres,
 * et valeurs métier (noms de Registration Agency, statuts OA…). Les libellés et la
 * mise en forme vivent ici, ce qui les rend modifiables sans relancer le pipeline
 * (et donc rétroactifs sur les anciens runs).
 *
 * Une phase sans entrée ici retombe sur l'affichage générique (résumé des compteurs
 * `PhaseMetrics` + tables avant/après).
 */

export type SummaryItem = { key: string; label: string };
export type TableColumn = { key: string; label: string; pct?: boolean; sign?: boolean };
export type PhaseView = {
  // Lignes de synthèse : pour chaque clé de `details.summary`, son libellé, dans l'ordre.
  summary?: SummaryItem[];
  // Tableau alimenté par `details.table.rows` (chaque ligne porte une `key` métier).
  table?: { firstColumnLabel: string; columns: TableColumn[]; total?: boolean };
};

export const PHASE_VIEWS: Record<string, PhaseView> = {
  resolve_ra: {
    summary: [
      { key: "new_prefixes", label: "Nouveaux préfixes" },
      { key: "resolved", label: "Résolus" },
    ],
    table: {
      firstColumnLabel: "Registration Agency",
      columns: [
        { key: "dois", label: "DOI", pct: true },
        { key: "prefixes", label: "Préfixes DOI", pct: true },
        { key: "new", label: "Run", sign: true },
      ],
      total: true,
    },
  },
  metadata_correction: {
    summary: [
      { key: "unary_examined", label: "SP examinées (unaire)" },
      { key: "unary_corrected", label: "Corrigées (unaire)" },
      { key: "cluster_examined", label: "SP examinées (cluster)" },
      { key: "cluster_corrected", label: "DOI corrigés (cluster)" },
    ],
    table: {
      firstColumnLabel: "Règle de correction",
      columns: [{ key: "count", label: "Nombre", pct: true }],
      total: true,
    },
  },
  oa_status: {
    summary: [
      { key: "stale", label: "Publications à vérifier" },
      { key: "checked", label: "Vérifiées (cap 10 000)" },
      { key: "updated", label: "Mises à jour" },
      { key: "unchanged", label: "Inchangées" },
      { key: "not_found", label: "Non trouvées" },
    ],
    table: {
      firstColumnLabel: "Statut OA",
      columns: [
        { key: "count", label: "Nombre", pct: true },
        { key: "delta", label: "Δ", sign: true },
      ],
      total: true,
    },
  },
};
