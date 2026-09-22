import { put } from './client';
import type { components } from './schema';

type OkResponse = components['schemas']['OkResponse'];

export function update(id: number, body: Record<string, unknown>): Promise<OkResponse> {
	return put<OkResponse>(`/api/monographs/${id}`, body);
}
