import { del, post, put } from './client';
import type { components } from './schema';

type StructureOut = components['schemas']['StructureOut'];
type StructureTutelleCreateResponse =
	components['schemas']['StructureTutelleCreateResponse'];
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

export function createTutelle(
	body: Record<string, unknown>
): Promise<StructureTutelleCreateResponse> {
	return post<StructureTutelleCreateResponse>('/api/structures/tutelles', body);
}

export function deleteTutelle(tutelleId: number): Promise<DeletedResponse> {
	return del<DeletedResponse>(`/api/structures/tutelles/${tutelleId}`);
}
