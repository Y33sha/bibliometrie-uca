import { post } from './client';
import type { components } from './schema';

type OkResponse = components['schemas']['OkResponse'];
type AddressReviewResponse = components['schemas']['AddressReviewResponse'];
type BatchUpdatedResponse = components['schemas']['BatchUpdatedResponse'];
type BatchCountryResponse = components['schemas']['BatchCountryResponse'];

export function review(
	addrId: number,
	body: Record<string, unknown>
): Promise<AddressReviewResponse> {
	return post<AddressReviewResponse>(`/api/addresses/${addrId}/review`, body);
}

export function batchReview(body: Record<string, unknown>): Promise<BatchUpdatedResponse> {
	return post<BatchUpdatedResponse>('/api/addresses/batch-review', body);
}

export function setCountry(addrId: number, body: Record<string, unknown>): Promise<OkResponse> {
	return post<OkResponse>(`/api/addresses/${addrId}/country`, body);
}

export function batchSetCountry(body: Record<string, unknown>): Promise<BatchCountryResponse> {
	return post<BatchCountryResponse>('/api/addresses/batch-country', body);
}
