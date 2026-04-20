import { del, post, put } from './client';
import type { components } from './schema';

type StructureOut = components['schemas']['StructureOut'];
type StructureRelationCreateResponse =
	components['schemas']['StructureRelationCreateResponse'];
type DeletedResponse = components['schemas']['DeletedResponse'];

export function create(body: Record<string, unknown>): Promise<StructureOut> {
	return post<StructureOut>('/api/structures', body);
}

export function update(id: number, body: Record<string, unknown>): Promise<StructureOut> {
	return put<StructureOut>(`/api/structures/${id}`, body);
}

export function remove(id: number): Promise<DeletedResponse> {
	return del<DeletedResponse>(`/api/structures/${id}`);
}

export function createRelation(
	body: Record<string, unknown>
): Promise<StructureRelationCreateResponse> {
	return post<StructureRelationCreateResponse>('/api/structure-relations', body);
}

export function deleteRelation(relId: number): Promise<DeletedResponse> {
	return del<DeletedResponse>(`/api/structure-relations/${relId}`);
}
