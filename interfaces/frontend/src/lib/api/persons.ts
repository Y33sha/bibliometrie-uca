import { del, patch, post } from './client';
import type { components } from './schema';

type AddIdentifierResponse = components['schemas']['AddIdentifierResponse'];
type IdentifierStatusResponse = components['schemas']['IdentifierStatusResponse'];
type IdentifierReassignResponse = components['schemas']['IdentifierReassignResponse'];
type MergeResponse = components['schemas']['MergeResponse'];
type OkResponse = components['schemas']['OkResponse'];
type RemovedResponse = components['schemas']['RemovedResponse'];
type NameFormStatusResponse = components['schemas']['NameFormStatusResponse'];
type DetachAuthorshipsResponse = components['schemas']['DetachAuthorshipsResponse'];

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

export function setRejected(personId: number, rejected: boolean): Promise<OkResponse> {
	return patch<OkResponse>(`/api/persons/${personId}/reject`, { rejected });
}

export function detachAuthorships(
	personId: number,
	body: Record<string, unknown>
): Promise<DetachAuthorshipsResponse> {
	return post<DetachAuthorshipsResponse>(`/api/persons/${personId}/detach-authorships`, body);
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

export function deleteIdentifier(
	personId: number,
	idType: string,
	idValue: string
): Promise<RemovedResponse> {
	const url = `/api/persons/${personId}/identifiers/${idType}/${encodeURIComponent(idValue)}`;
	return del<RemovedResponse>(url);
}

export function setIdentifierStatus(
	identId: number,
	status: string
): Promise<IdentifierStatusResponse> {
	return patch<IdentifierStatusResponse>(`/api/person-identifiers/${identId}/status`, { status });
}

export function reassignIdentifier(
	identId: number,
	body: Record<string, unknown>
): Promise<IdentifierReassignResponse> {
	return patch<IdentifierReassignResponse>(`/api/person-identifiers/${identId}/reassign`, body);
}

export function markDistinct(
	personIdA: number,
	personIdB: number
): Promise<unknown> {
	return post('/api/admin/persons/mark-distinct', {
		person_id_a: personIdA,
		person_id_b: personIdB
	});
}
