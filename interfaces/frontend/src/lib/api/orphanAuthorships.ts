import { post } from './client';

export function assign(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/admin/orphan-authorships/assign', body);
}

export function batchAssign(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/admin/orphan-authorships/batch-assign', body);
}
