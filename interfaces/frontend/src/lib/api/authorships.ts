import { patch } from './client';

export function exclude(authorshipId: number): Promise<unknown> {
	return patch(`/api/authorships/${authorshipId}/exclude`);
}
