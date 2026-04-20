/**
 * Types partagés par la page `admin/persons` et ses sous-composants.
 *
 * Les types de réponses API proviennent du schéma OpenAPI généré
 * (`$lib/api/schema.ts`) ; seuls les états d'UI locaux restent définis ici.
 */

import type { components } from "$lib/api/schema";

// ── Types API (générés) ──
export type PersonStats = components["schemas"]["PersonsStatsResponse"];
export type LinkedAuthor = components["schemas"]["LinkedAuthorOut"];
export type PersonIdentifier = components["schemas"]["PersonIdentifierOut"];
export type NameForm = components["schemas"]["NameFormSummaryOut"];
export type Person = components["schemas"]["PersonOut"];
export type PersonListResponse = components["schemas"]["PersonListResponse"];
export type OtherPerson = components["schemas"]["OtherPersonOut"];
export type PersonSearchResult = components["schemas"]["PersonSearchResult"];

// ── Extensions UI (champs ajoutés côté front) ──
export type DetachAuthorship = components["schemas"]["NameFormAuthorshipRef"] & {
  checked: boolean;
};

// ── États UI locaux ──
export interface EditNameState {
  personId: number;
  lastName: string;
  firstName: string;
  rejected: boolean;
}

export interface DetachModalState {
  personId: number;
  nameForm: string;
  authorships: DetachAuthorship[];
  otherPersons: OtherPerson[];
  loading: boolean;
}

export interface IdFormState {
  id_type: string;
  id_value: string;
  error: string;
}
