import { del, post, put } from './client';

export function create(body: Record<string, unknown>): Promise<{ id: number }> {
	return post<{ id: number }>('/api/perimeters', body);
}

export function update(id: number, body: Record<string, unknown>): Promise<unknown> {
	return put(`/api/perimeters/${id}`, body);
}

export function remove(id: number): Promise<null> {
	return del<null>(`/api/perimeters/${id}`);
}
