import { api, post } from './client';
import type { components } from './schema';

export type MergeCandidate = components['schemas']['MergeCandidateOut'];
type PublicationMergeResult = components['schemas']['PublicationMergeResult'];

/** Publications fusionnables avec `id` : titres proches du sien, ou, avec `query`, la publication de cet identifiant, de ce DOI, ou les titres qui contiennent ces mots. */
export function mergeCandidates(
	id: number,
	query = '',
	request: <T>(url: string) => Promise<T> = api,
): Promise<MergeCandidate[]> {
	const q = query ? `?q=${encodeURIComponent(query)}` : '';
	return request<MergeCandidate[]>(`/api/publications/${id}/merge-candidates${q}`);
}

/**
 * Aperçu de la fusion manuelle de deux publications : publication conservée et nombre de conflits d'auteurs. Le backend applique la fusion puis l'annule : rien ne persiste, mais l'appel est une action admin, d'où le POST.
 */
export function mergePreview(id: number, otherId: number): Promise<PublicationMergeResult> {
	return post<PublicationMergeResult>(`/api/publications/${id}/merge-preview`, {
		other_id: otherId,
	});
}

export function merge(id: number, otherId: number): Promise<PublicationMergeResult> {
	return post<PublicationMergeResult>(`/api/publications/${id}/merge`, { other_id: otherId });
}
