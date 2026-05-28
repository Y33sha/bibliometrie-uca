import { api, post, put } from './client';

export function update(id: number, body: Record<string, unknown>): Promise<unknown> {
	return put(`/api/journals/${id}`, body);
}

export function merge(targetId: number, sourceId: number): Promise<unknown> {
	return post(`/api/journals/${targetId}/merge`, { source_id: sourceId });
}

/**
 * Preview de l'impact d'un changement de `journal_type` sur le `doc_type` canonique
 * des publications rattachées. Dry-run pur côté backend (aucune écriture).
 */
export function typeChangeImpact(id: number, newType: string): Promise<{ count: number }> {
	return api(`/api/journals/${id}/type-change-impact?new_type=${encodeURIComponent(newType)}`);
}
