import { api, post } from './client';
import type { components } from './schema';

type AuthCheckResponse = components['schemas']['AuthCheckResponse'];
type OkResponse = components['schemas']['OkResponse'];

export function check(): Promise<AuthCheckResponse> {
	return api<AuthCheckResponse>('/api/auth/check');
}

export function login(username: string, password: string): Promise<OkResponse> {
	return post<OkResponse>('/api/auth/login', { username, password });
}

export function logout(): Promise<OkResponse> {
	return post<OkResponse>('/api/auth/logout');
}
