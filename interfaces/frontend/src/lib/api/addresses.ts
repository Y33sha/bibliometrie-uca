import { post } from './client';

export function review(addrId: number, body: Record<string, unknown>): Promise<unknown> {
	return post(`/api/addresses/${addrId}/review`, body);
}

export function batchReview(body: Record<string, unknown>): Promise<unknown> {
	return post('/api/addresses/batch-review', body);
}

export function setCountry(addrId: number, body: Record<string, unknown>): Promise<unknown> {
	return post(`/api/addresses/${addrId}/country`, body);
}
