import { del, post, put } from './client';

export function create(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/structures', body);
}

export function update(id: number, body: Record<string, unknown>): Promise<unknown> {
	return put(`/api/structures/${id}`, body);
}

export function remove(id: number): Promise<null> {
	return del<null>(`/api/structures/${id}`);
}

export function createRelation(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/structure-relations', body);
}

export function deleteRelation(relId: number): Promise<null> {
	return del<null>(`/api/structure-relations/${relId}`);
}
