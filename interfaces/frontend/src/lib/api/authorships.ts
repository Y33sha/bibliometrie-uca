import { patch } from './client';
import type { components } from './schema';

type OkResponse = components['schemas']['OkResponse'];

export function exclude(authorshipId: number): Promise<OkResponse> {
	return patch<OkResponse>(`/api/authorships/${authorshipId}/exclude`);
}
