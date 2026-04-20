import { post } from './client';

/** Fusion de doublons publications (pas personnes — voir persons.merge). */
export function mergePublications(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/admin/duplicates/merge', body);
}

export function markPublicationsDistinct(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/admin/duplicates/mark-distinct', body);
}
