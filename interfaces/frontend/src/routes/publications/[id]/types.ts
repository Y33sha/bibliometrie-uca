/**
 * Types partagés par la page `publications/[id]` et ses sous-composants.
 * Co-localisés avec la route car ils ne sont pas réutilisés ailleurs.
 *
 * Les types de réponse API sont alias des types générés depuis OpenAPI
 * (`$lib/api/schema`). `SourceRow` est propre au front (construit côté
 * client pour comparer les sources HAL/OA/WoS).
 */

import type { components } from "$lib/api/schema";

export type PubDetail = components["schemas"]["PublicationDetailCore"];
export type Source = components["schemas"]["SourcePublicationOut"];
export type Authorship = components["schemas"]["ConsolidatedAuthorshipOut"];
export type SourceAuthorship = components["schemas"]["SourceAuthorshipOut"];
export type StructInfo = components["schemas"]["StructureInfo"];
export type ThesisAuthorship = components["schemas"]["ThesesAuthorshipOut"];
export type ThesisMeta = components["schemas"]["ThesisMeta"];
export type Subject = components["schemas"]["SubjectOut"];
export type RelatedPublication = components["schemas"]["RelatedPublicationOut"];
export type PubResponse = components["schemas"]["PublicationDetailResponse"];

export interface SourceRow {
  position: number;
  hal: SourceAuthorship | null;
  oa: SourceAuthorship | null;
  wos: SourceAuthorship | null;
  scanr: SourceAuthorship | null;
  conflict: boolean;
}

/** Nom d'une structure via son id (acronyme si dispo, sinon nom, sinon `#id`). */
export function structLabel(structures: Record<string, StructInfo>, id: number): string {
  const s = structures[String(id)];
  return s ? s.acronym || s.name : `#${id}`;
}

export function structIsLabo(structures: Record<string, StructInfo>, id: number): boolean {
  return structures[String(id)]?.type === "labo";
}

/** Tooltip résumé des affiliations brutes + structures identifiées. */
export function structsTooltip(
  a: SourceAuthorship,
  structures: Record<string, StructInfo>,
): string {
  const parts: string[] = [];
  if (a.raw_affiliation) {
    parts.push(`<em>${a.raw_affiliation}</em>`);
  }
  if (a.structure_ids?.length) {
    parts.push(
      `Structures identifiées : ${a.structure_ids.map((sid) => structLabel(structures, sid)).join(", ")}`,
    );
  }
  return parts.join("<br>") || "";
}
