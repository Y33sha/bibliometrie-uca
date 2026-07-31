import { post, put } from './client';
import type { components } from './schema';

type OkResponse = components['schemas']['OkResponse'];
type MergeResponse = components['schemas']['MergeResponse'];
type JournalTypeChangeImpact = components['schemas']['JournalTypeChangeImpact'];

export function update(id: number, body: Record<string, unknown>): Promise<OkResponse> {
	return put<OkResponse>(`/api/journals/${id}`, body);
}

export function merge(targetId: number, sourceId: number): Promise<MergeResponse> {
	return post<MergeResponse>(`/api/journals/${targetId}/merge`, { source_id: sourceId });
}

/**
 * Preview de l'impact d'un changement de `journal_type` sur le `doc_type` canonique des publications rattachées. Le backend applique le changement puis l'annule : rien ne persiste, mais l'appel est une action admin, d'où le POST.
 */
export function typeChangeImpact(id: number, newType: string): Promise<JournalTypeChangeImpact> {
	return post<JournalTypeChangeImpact>(`/api/journals/${id}/type-change-impact`, {
		journal_type: newType
	});
}
