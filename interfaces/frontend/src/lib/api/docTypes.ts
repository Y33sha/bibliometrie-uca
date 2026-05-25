import { api } from './client';
import type { components } from './schema';

export type DocTypeListResponse = components['schemas']['DocTypeListResponse'];

export function list(): Promise<DocTypeListResponse> {
	return api('/api/doc-types');
}
