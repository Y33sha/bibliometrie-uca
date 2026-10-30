import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const check = vi.fn();
vi.mock('$app/paths', () => ({ resolve: (path: string) => '/' + path }));
vi.mock('#lib/api/index.js', () => ({ auth: { check } }));

let storage: Map<string, string>;

beforeEach(() => {
	storage = new Map();
	vi.stubGlobal('localStorage', {
		getItem: (key: string) => storage.get(key) ?? null,
		setItem: (key: string, value: string) => storage.set(key, value),
	});
	vi.resetModules();
	check.mockReset();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('adminLook', () => {
	it("prend l'aspect admin de la dernière session tant que la session n'est pas lue", async () => {
		storage.set('session-admin', '1');
		const { adminLook } = await import('./session.svelte');
		expect(adminLook()).toBe(true);
	});

	it('suit le rôle de la session lue et le retient pour le prochain onglet', async () => {
		storage.set('session-admin', '1');
		check.mockResolvedValue({ authenticated: false, roles: [] });
		const { adminLook, loadSession } = await import('./session.svelte');
		await loadSession();
		expect(adminLook()).toBe(false);
		expect(storage.get('session-admin')).toBe('0');
	});

	it("retient le rôle admin d'une session lue", async () => {
		check.mockResolvedValue({ authenticated: true, login: 'admin', roles: ['admin'] });
		const { adminLook, loadSession } = await import('./session.svelte');
		expect(adminLook()).toBe(false);
		await loadSession();
		expect(adminLook()).toBe(true);
		expect(storage.get('session-admin')).toBe('1');
	});
});
