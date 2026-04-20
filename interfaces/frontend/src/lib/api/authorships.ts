import { patch } from './client';
import type { components } from './schema';

type AuthorshipExcludeResponse = components['schemas']['AuthorshipExcludeResponse'];

export function exclude(authorshipId: number): Promise<AuthorshipExcludeResponse> {
	return patch<AuthorshipExcludeResponse>(`/api/authorships/${authorshipId}/exclude`);
}
