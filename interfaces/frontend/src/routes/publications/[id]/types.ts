/**
 * Types partagés par la page `publications/[id]` et ses sous-composants. Co-localisés avec la route car ils ne sont pas réutilisés ailleurs.
 *
 * Les types de réponse API sont alias des types générés depuis OpenAPI (`#lib/api/schema.js`).
 */

import type { components } from "#lib/api/schema.js";

export type PubDetail = components["schemas"]["PublicationDetailCore"];
export type Source = components["schemas"]["SourceRecordOut"];
export type Contribution = components["schemas"]["ConsolidatedContributionOut"];
export type { StructInfo } from "#lib/structureLabels.js";
export type ThesisContribution = components["schemas"]["ThesesContributionOut"];
export type ThesisMeta = components["schemas"]["ThesisMeta"];
export type Subject = components["schemas"]["SubjectOut"];
export type RelatedPublication = components["schemas"]["RelatedPublicationOut"];
export type ExternalId = components["schemas"]["ExternalIdentifierOut"];
export type AccessLink = components["schemas"]["AccessLinkOut"];
export type PubResponse = components["schemas"]["PublicationDetailResponse"];
