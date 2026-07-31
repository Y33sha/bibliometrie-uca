import { post } from './client';
import type { components } from './schema';

type MergeResponse = components['schemas']['MergeResponse'];
type OkResponse = components['schemas']['OkResponse'];

/** Fusion de doublons publications (pas personnes — voir persons.merge). */
export function mergePublications(body: Record<string, unknown>): Promise<MergeResponse> {
	return post<MergeResponse>('/api/publications/duplicates/merge', body);
}

export function markPublicationsDistinct(body: Record<string, unknown>): Promise<OkResponse> {
	return post<OkResponse>('/api/publications/duplicates/mark-distinct', body);
}
