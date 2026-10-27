import { api, del, post, put } from './client';
import type { components } from './schema';
import { compareStructureLabels } from '../structureLabels';

type StructureListItem = components['schemas']['StructureListItem'];
type StructureOut = components['schemas']['StructureOut'];
type StructureTutelleCreateResponse =
	components['schemas']['StructureTutelleCreateResponse'];
type DeletedResponse = components['schemas']['DeletedResponse'];

/**
 * Structures dont la détection d'adresses s'évalue, hors sites, triées par libellé.
 *
 * Un site sert seulement de contexte au matching des formes de nom.
 */
export async function listDetectable(): Promise<StructureListItem[]> {
	const all = await api<StructureListItem[]>('/api/structures/all');
	return all.filter((s) => s.type !== 'site').sort(compareStructureLabels);
}

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
