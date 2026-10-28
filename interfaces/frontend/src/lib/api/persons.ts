import { del, patch, post } from './client';
import type { components } from './schema';

type AddIdentifierResponse = components['schemas']['AddIdentifierResponse'];
type IdentifierStatusResponse = components['schemas']['IdentifierStatusResponse'];
type MergeResponse = components['schemas']['MergeResponse'];
type OkResponse = components['schemas']['OkResponse'];
type NameFormStatusResponse = components['schemas']['NameFormStatusResponse'];
type DetachContributionsResponse = components['schemas']['DetachContributionsResponse'];
export type PersonExclusion = components['schemas']['PersonExclusion'];

export function merge(targetId: number, sourceId: number): Promise<MergeResponse> {
	return post<MergeResponse>(`/api/persons/${targetId}/merge`, { source_id: sourceId });
}

export function rename(
	personId: number,
	lastName: string,
	firstName: string
): Promise<OkResponse> {
	return patch<OkResponse>(`/api/persons/${personId}/name`, {
		last_name: lastName,
		first_name: firstName
	});
}

export function setExclusion(
	personId: number,
	exclusion: PersonExclusion | null
): Promise<OkResponse> {
	return patch<OkResponse>(`/api/persons/${personId}/exclusion`, { exclusion });
}

export function detachContributions(
	personId: number,
	body: Record<string, unknown>
): Promise<DetachContributionsResponse> {
	return post<DetachContributionsResponse>(`/api/persons/${personId}/detach-contributions`, body);
}

export function updateNameFormStatus(
	personId: number,
	nameForm: string,
	status: 'pending' | 'confirmed' | 'rejected'
): Promise<NameFormStatusResponse> {
	return patch<NameFormStatusResponse>(`/api/persons/${personId}/name-forms/status`, {
		name_form: nameForm,
		status
	});
}

export function addIdentifier(
	personId: number,
	body: Record<string, unknown>
): Promise<AddIdentifierResponse> {
	return post<AddIdentifierResponse>(`/api/persons/${personId}/identifiers`, body);
}

export function setIdentifierStatus(
	identId: number,
	status: string
): Promise<IdentifierStatusResponse> {
	return patch<IdentifierStatusResponse>(`/api/persons/identifiers/${identId}/status`, { status });
}

export function markDistinct(
	personIdA: number,
	personIdB: number
): Promise<OkResponse> {
	return post<OkResponse>('/api/persons/mark-distinct', {
		person_id_a: personIdA,
		person_id_b: personIdB
	});
}

export function unmarkDistinct(personId: number, otherId: number): Promise<OkResponse> {
	return del<OkResponse>(`/api/persons/${personId}/distinct-persons/${otherId}`);
}
