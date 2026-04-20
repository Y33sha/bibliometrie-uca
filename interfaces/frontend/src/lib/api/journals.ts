import { post, put } from './client';

export function update(id: number, body: Record<string, unknown>): Promise<unknown> {
	return put(`/api/journals/${id}`, body);
}

export function merge(targetId: number, sourceId: number): Promise<unknown> {
	return post(`/api/journals/${targetId}/merge`, { source_id: sourceId });
}
