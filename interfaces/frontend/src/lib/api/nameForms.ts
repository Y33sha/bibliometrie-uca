import { del, post, put } from './client';

export function create(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/name-forms', body);
}

export function update(formId: number, body: Record<string, unknown>): Promise<unknown> {
	return put(`/api/name-forms/${formId}`, body);
}

export function remove(formId: number): Promise<null> {
	return del<null>(`/api/name-forms/${formId}`);
}
