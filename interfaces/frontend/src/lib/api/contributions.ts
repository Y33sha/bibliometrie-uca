import { patch } from './client';
import type { components } from './schema';

type OkResponse = components['schemas']['OkResponse'];

export function exclude(contributionId: number): Promise<OkResponse> {
	return patch<OkResponse>(`/api/contributions/${contributionId}/exclude`);
}
