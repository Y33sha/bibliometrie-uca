import { post } from './client';
import type { components } from './schema';

type OrphanAssignResponse = components['schemas']['OrphanAssignResponse'];
type OrphanBatchAssignResponse = components['schemas']['OrphanBatchAssignResponse'];

export function assign(body: Record<string, unknown>): Promise<OrphanAssignResponse> {
	return post<OrphanAssignResponse>('/api/admin/orphan-authorships/assign', body);
}

export function batchAssign(body: Record<string, unknown>): Promise<OrphanBatchAssignResponse> {
	return post<OrphanBatchAssignResponse>('/api/admin/orphan-authorships/batch-assign', body);
}
