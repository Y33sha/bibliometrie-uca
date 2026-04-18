import { base } from '$app/paths';

const controllers: Map<string, AbortController> = new Map();

// Promesse qui ne se résout jamais — utilisée pour "avaler" les requêtes annulées
const CANCELLED = new Promise<never>(() => {});

/**
 * Fetch API avec annulation automatique des requêtes précédentes.
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
			if (!res.ok) throw new Error(`API error ${res.status}`);
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
	if (!res.ok) throw new Error(`API error ${res.status}`);
	return res.json();
}
