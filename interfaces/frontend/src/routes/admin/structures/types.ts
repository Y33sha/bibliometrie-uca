/**
 * Types et helpers partagés par la page `admin/structures` et ses sous-composants.
 *
 * Les types de réponses API proviennent du schéma OpenAPI généré (`$lib/api/schema.ts`) ; seuls les états d'UI locaux et helpers restent ici.
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

// Longueur (caractères) au-dessous de laquelle une forme de nom exige une frontière de mot. Alignée sur `domain.structures.name_forms.SHORT_FORM_MAX_LENGTH` (invariant verrouillé côté base par une contrainte CHECK).
export const SHORT_FORM_MAX_LENGTH = 6;

// ── Helpers ──
export function halCollectionUrl(code: string): string {
  return `https://hal.science/search/index/?qa%5BcollCode_s%5D%5B%5D=${code}`;
}

export const ROR_FORMAT_ERROR =
  "Format ROR invalide. Attendu : 0xxxxxxxxx (ou https://ror.org/0xxxxxxxxx)";

/**
 * Normalise un ROR ID vers sa forme canonique (id court 9 caractères), acceptant une URL `https://ror.org/…` ou un id nu. Retourne la forme canonique, `""` pour une entrée vide, ou `null` si le format est invalide. Le backend re-normalise de toute façon via le value object RorId.
 */
export function normalizeRorId(raw: string): string | null {
  const ror = raw.trim().replace(/^https?:\/\/ror\.org\//, "");
  if (!ror) return "";
  return /^0[a-z0-9]{8}$/.test(ror) ? ror : null;
}

/**
 * Construit le payload `api_ids` (source → liste d'identifiants) depuis les champs texte du formulaire, les identifiants étant séparés par des virgules. Retourne `null` si aucune source n'est renseignée.
 */
export function buildApiIds(
  apiIds: Record<string, string>,
): Record<string, string[]> | null {
  const result: Record<string, string[]> = {};
  let hasAny = false;
  for (const src of API_SOURCES) {
    const raw = (apiIds[src] || "").trim();
    if (raw) {
      result[src] = raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      hasAny = true;
    }
  }
  return hasAny ? result : null;
}
