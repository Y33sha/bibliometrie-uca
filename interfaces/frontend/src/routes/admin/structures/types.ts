/**
 * Types et helpers partagés par la page `admin/structures` et ses sous-composants.
 *
 * Les types de réponses API proviennent du schéma OpenAPI généré
 * (`$lib/api/schema.ts`) ; seuls les états d'UI locaux et helpers restent ici.
 */

import type { components } from "$lib/api/schema";

// ── Types API (générés) ──
export type Structure = components["schemas"]["StructureOut"];
export type StructureListItem = components["schemas"]["StructureListItem"];
export type Perimeter = components["schemas"]["PerimeterOut"];
export type RelatedStructure = components["schemas"]["RelatedStructureOut"];
export type NameForm = components["schemas"]["NameFormOut"];
export type StructureDetail = components["schemas"]["StructureDetailResponse"];

// ── État UI local ──
export interface EditFormState {
  id: number;
  form_text: string;
  is_word_boundary: boolean;
  is_excluding: boolean;
}

// ── Constantes ──

export const API_SOURCES = ["openalex", "wos", "scanr", "theses"] as const;

export const API_SOURCE_LABELS: Record<string, string> = {
  openalex: "OpenAlex (institution lineage IDs)",
  wos: "WoS (Organization-Enhanced)",
  scanr: "ScanR (SIREN)",
  theses: "theses.fr (PPN IdRef)",
};

// ── Helpers ──
export function halCollectionUrl(code: string): string {
  return `https://hal.science/search/index/?qa%5BcollCode_s%5D%5B%5D=${code}`;
}
