import { post, put } from './client';

export function update(id: number, body: Record<string, unknown>): Promise<unknown> {
	return put(`/api/publishers/${id}`, body);
}

export function merge(targetId: number, sourceId: number): Promise<unknown> {
	return post(`/api/publishers/${targetId}/merge`, { source_id: sourceId });
}
