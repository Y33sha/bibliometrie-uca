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

export function batchSetCountry(body: Record<string, unknown>): Promise<{ updated: number }> {
	return post<{ updated: number }>('/api/addresses/batch-country', body);
}
