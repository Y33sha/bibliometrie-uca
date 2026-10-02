/**
 * Types partagés par la page `admin/persons` et ses sous-composants.
 *
 * Les types de réponses API proviennent du schéma OpenAPI généré (`$lib/api/schema.ts`) ; seuls les états d'UI locaux restent définis ici.
 */

import type { components } from "$lib/api/schema";

// ── Types API (générés) ──
export type PersonIdentifier = components["schemas"]["PersonIdentifierOut"];
export type NameForm = components["schemas"]["NameFormSummaryOut"];
export type Person = components["schemas"]["PersonOut"];
export type PersonListResponse = components["schemas"]["PersonListResponse"];
export type OtherPerson = components["schemas"]["OtherPersonOut"];
export type PersonSearchResult = components["schemas"]["PersonSearchResult"];
export type PersonExclusion = components["schemas"]["PersonExclusion"];

/** Filtre de la liste sur l'exclusion : toutes les personnes (""), les retenues, les exclues, ou les exclues pour un motif. */
export type ExclusionFilter = "" | "retained" | "excluded" | PersonExclusion;

/** Paramètres de requête `/api/persons` qui traduisent un filtre d'exclusion. */
export function setExclusionParams(params: URLSearchParams, filter: ExclusionFilter): void {
  if (filter === "retained") params.set("excluded", "false");
  else if (filter === "excluded") params.set("excluded", "true");
  else if (filter) params.set("exclusion", filter);
}

// ── Extensions UI (champs ajoutés côté front) ──
type NameFormAuthorshipRef = components["schemas"]["NameFormAuthorshipRef"];

/**
 * Publication regroupant toutes ses sources observées sous une même forme de nom. Le rejet porte sur la publication entière (toutes ses sources) : la modale affiche une ligne par publication, pas par source.
 */
export interface DetachPublication {
  pub_id: number;
  title: string;
  pub_year: number | null;
  sources: Pick<NameFormAuthorshipRef, "source" | "source_authorship_id">[];
  checked: boolean;
}

// ── États UI locaux ──
export interface DetachModalState {
  personId: number;
  nameForm: string;
  publications: DetachPublication[];
  otherPersons: OtherPerson[];
  loading: boolean;
}

export interface IdFormState {
  id_type: string;
  id_value: string;
  error: string;
}
