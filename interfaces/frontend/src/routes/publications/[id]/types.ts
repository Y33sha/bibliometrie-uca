/**
 * Types partagés par la page `publications/[id]` et ses sous-composants. Co-localisés avec la route car ils ne sont pas réutilisés ailleurs.
 *
 * Les types de réponse API sont alias des types générés depuis OpenAPI (`$lib/api/schema`).
 */

import type { components } from "$lib/api/schema";

export type PubDetail = components["schemas"]["PublicationDetailCore"];
export type Source = components["schemas"]["SourcePublicationOut"];
export type Authorship = components["schemas"]["ConsolidatedAuthorshipOut"];
export type { StructInfo } from "$lib/structureLabels";
export type ThesisAuthorship = components["schemas"]["ThesesAuthorshipOut"];
export type ThesisMeta = components["schemas"]["ThesisMeta"];
export type Subject = components["schemas"]["SubjectOut"];
export type RelatedPublication = components["schemas"]["RelatedPublicationOut"];
export type ExternalId = components["schemas"]["ExternalIdentifierOut"];
export type PubResponse = components["schemas"]["PublicationDetailResponse"];
