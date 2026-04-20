import { del, patch, post } from './client';

export function merge(targetId: number, sourceId: number): Promise<unknown> {
	return post(`/api/persons/${targetId}/merge`, { source_id: sourceId });
}

export function rename(personId: number, lastName: string, firstName: string): Promise<unknown> {
	return patch(`/api/persons/${personId}/name`, {
		last_name: lastName,
		first_name: firstName
	});
}

export function setRejected(personId: number, rejected: boolean): Promise<unknown> {
	return patch(`/api/persons/${personId}/reject`, { rejected });
}

export function detachAuthorships(
	personId: number,
	body: Record<string, unknown>
): Promise<unknown> {
	return post(`/api/persons/${personId}/detach-authorships`, body);
}

export function detachNameForm(
	personId: number,
	body: Record<string, unknown>
): Promise<unknown> {
	return post(`/api/persons/${personId}/detach-name-form`, body);
}

export function addIdentifier(
	personId: number,
	body: Record<string, unknown>
): Promise<unknown> {
	return post(`/api/persons/${personId}/identifiers`, body);
}

export function deleteIdentifier(
	personId: number,
	idType: string,
	idValue: string
): Promise<null> {
	const url = `/api/persons/${personId}/identifiers/${idType}/${encodeURIComponent(idValue)}`;
	return del<null>(url);
}

export function setIdentifierStatus(identId: number, status: string): Promise<unknown> {
	return patch(`/api/person-identifiers/${identId}/status`, { status });
}

export function reassignIdentifier(
	identId: number,
	body: Record<string, unknown>
): Promise<unknown> {
	return patch(`/api/person-identifiers/${identId}/reassign`, body);
}

export function markDistinct(
	personIdA: number,
	personIdB: number
): Promise<unknown> {
	return post('/api/admin/person-duplicates/mark-distinct', {
		person_id_a: personIdA,
		person_id_b: personIdB
	});
}
