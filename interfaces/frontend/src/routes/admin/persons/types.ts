/**
 * Types partagés par la page `admin/persons` et ses sous-composants.
 *
 * Les types de réponses API proviennent du schéma OpenAPI généré
 * (`$lib/api/schema.ts`) ; seuls les états d'UI locaux restent définis ici.
 */

import type { components } from "$lib/api/schema";

// ── Types API (générés) ──
export type PersonStats = components["schemas"]["PersonsStatsResponse"];
export type PersonIdentifier = components["schemas"]["PersonIdentifierOut"];
export type NameForm = components["schemas"]["NameFormSummaryOut"];
export type Person = components["schemas"]["PersonOut"];
export type PersonListResponse = components["schemas"]["PersonListResponse"];
export type OtherPerson = components["schemas"]["OtherPersonOut"];
export type PersonSearchResult = components["schemas"]["PersonSearchResult"];

// ── Extensions UI (champs ajoutés côté front) ──
type NameFormAuthorshipRef = components["schemas"]["NameFormAuthorshipRef"];

/**
 * Publication regroupant toutes ses sources observées sous une même forme de
 * nom. Le rejet porte sur la publication entière (toutes ses sources), donc la
 * modale affiche une ligne par publication, pas par source.
 */
export interface DetachPublication {
  pub_id: number;
  title: string;
  pub_year: number | null;
  sources: Pick<NameFormAuthorshipRef, "source" | "authorship_id">[];
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
