import { post, put } from './client';
import type { components } from './schema';

type OkResponse = components['schemas']['OkResponse'];
type MergeResponse = components['schemas']['MergeResponse'];
type SerialTypeChangeImpact = components['schemas']['SerialTypeChangeImpact'];

export function update(id: number, body: Record<string, unknown>): Promise<OkResponse> {
	return put<OkResponse>(`/api/serials/${id}`, body);
}

export function merge(targetId: number, sourceId: number): Promise<MergeResponse> {
	return post<MergeResponse>(`/api/serials/${targetId}/merge`, { source_id: sourceId });
}

/**
 * Preview de l'impact d'un changement de `serial_type` sur le `doc_type` canonique des publications rattachées. Le backend applique le changement puis l'annule : rien ne persiste, mais l'appel est une action admin, d'où le POST.
 */
export function typeChangeImpact(id: number, newType: string): Promise<SerialTypeChangeImpact> {
	return post<SerialTypeChangeImpact>(`/api/serials/${id}/type-change-impact`, {
		serial_type: newType
	});
}
