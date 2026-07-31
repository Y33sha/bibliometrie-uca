import { post, put } from './client';
import type { components } from './schema';

type OkResponse = components['schemas']['OkResponse'];
type MergeResponse = components['schemas']['MergeResponse'];

export function update(id: number, body: Record<string, unknown>): Promise<OkResponse> {
	return put<OkResponse>(`/api/publishers/${id}`, body);
}

export function merge(targetId: number, sourceId: number): Promise<MergeResponse> {
	return post<MergeResponse>(`/api/publishers/${targetId}/merge`, { source_id: sourceId });
}
