import { del, post, put } from './client';
import type { components } from './schema';

type NameFormOut = components['schemas']['NameFormOut'];
type DeletedResponse = components['schemas']['DeletedResponse'];

export function create(body: Record<string, unknown>): Promise<NameFormOut> {
	return post<NameFormOut>('/api/structures/name-forms', body);
}

export function update(formId: number, body: Record<string, unknown>): Promise<NameFormOut> {
	return put<NameFormOut>(`/api/structures/name-forms/${formId}`, body);
}

export function remove(formId: number): Promise<DeletedResponse> {
	return del<DeletedResponse>(`/api/structures/name-forms/${formId}`);
}
