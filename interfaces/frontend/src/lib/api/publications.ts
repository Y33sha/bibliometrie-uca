import { post } from './client';

export function excludeSourceAuthorship(
	source: string,
	authorshipId: number,
	body?: Record<string, unknown>
): Promise<unknown> {
	return post(`/api/source-authorships/${source}/${authorshipId}/exclude`, body);
}
