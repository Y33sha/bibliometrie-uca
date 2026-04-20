import { base } from '$app/paths';

const controllers: Map<string, AbortController> = new Map();

// Promesse qui ne se résout jamais — utilisée pour "avaler" les requêtes annulées
const CANCELLED = new Promise<never>(() => {});

export class ApiError extends Error {
	status: number;
	detail: unknown;
	constructor(status: number, detail: unknown) {
		super(`API error ${status}`);
		this.status = status;
		this.detail = detail;
	}
}

async function parseError(res: Response): Promise<unknown> {
	try {
		return await res.json();
	} catch {
		return await res.text().catch(() => null);
	}
}

/**
 * GET avec annulation automatique des requêtes précédentes.
 * Si `key` est fourni, toute requête précédente avec la même clé est annulée.
 * Une requête annulée ne résout ni ne rejette — elle disparaît silencieusement.
 *
 * Usage : api('/api/publications?...', { key: 'pub-list' })
 */
export async function api<T>(url: string, opts?: { key?: string }): Promise<T> {
	const key = opts?.key;
	if (key) {
		const prev = controllers.get(key);
		if (prev) prev.abort();
		const ctrl = new AbortController();
		controllers.set(key, ctrl);
		try {
			const res = await fetch(base + url, { signal: ctrl.signal });
			if (!res.ok) throw new ApiError(res.status, await parseError(res));
			return res.json();
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') {
				return CANCELLED as T;
			}
			throw e;
		} finally {
			if (controllers.get(key) === ctrl) controllers.delete(key);
		}
	}
	const res = await fetch(base + url);
	if (!res.ok) throw new ApiError(res.status, await parseError(res));
	return res.json();
}

type Method = 'POST' | 'PUT' | 'PATCH' | 'DELETE';

/**
 * Helper interne pour les mutations. Gère le JSON body, les erreurs HTTP
 * avec extraction du `detail`, et le cas "204 No Content" (retourne null).
 */
async function mutate<T>(method: Method, url: string, body?: unknown): Promise<T> {
	const init: RequestInit = { method };
	if (body !== undefined) {
		init.headers = { 'Content-Type': 'application/json' };
		init.body = JSON.stringify(body);
	}
	const res = await fetch(base + url, init);
	if (!res.ok) throw new ApiError(res.status, await parseError(res));
	if (res.status === 204 || res.headers.get('content-length') === '0') {
		return null as T;
	}
	const text = await res.text();
	return (text ? JSON.parse(text) : null) as T;
}

export function post<T>(url: string, body?: unknown): Promise<T> {
	return mutate<T>('POST', url, body);
}

export function put<T>(url: string, body?: unknown): Promise<T> {
	return mutate<T>('PUT', url, body);
}

export function patch<T>(url: string, body?: unknown): Promise<T> {
	return mutate<T>('PATCH', url, body);
}

export function del<T = null>(url: string): Promise<T> {
	return mutate<T>('DELETE', url);
}
