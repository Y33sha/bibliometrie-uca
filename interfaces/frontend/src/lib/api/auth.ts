import { api, post } from './client';

export type AuthCheck = { authenticated: boolean; user?: string };
export type HealthResponse = { status: string; sandbox?: boolean; [k: string]: unknown };

export function check(): Promise<AuthCheck> {
	return api<AuthCheck>('/api/auth/check');
}

export function login(username: string, password: string): Promise<AuthCheck> {
	return post<AuthCheck>('/api/auth/login', { username, password });
}

export function logout(): Promise<null> {
	return post<null>('/api/auth/logout');
}

export function health(): Promise<HealthResponse> {
	return api<HealthResponse>('/api/health');
}
