import { del, post, put } from './client';
import type { components } from './schema';

type CreatedIdResponse = components['schemas']['CreatedIdResponse'];
type OkResponse = components['schemas']['OkResponse'];

export function create(body: Record<string, unknown>): Promise<CreatedIdResponse> {
	return post<CreatedIdResponse>('/api/perimeters', body);
}

export function update(id: number, body: Record<string, unknown>): Promise<OkResponse> {
	return put<OkResponse>(`/api/perimeters/${id}`, body);
}

export function remove(id: number): Promise<OkResponse> {
	return del<OkResponse>(`/api/perimeters/${id}`);
}
