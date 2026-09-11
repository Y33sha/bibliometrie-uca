import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { loadProjectEnv } from './project-env.js';

function project(): string {
	const root = mkdtempSync(join(tmpdir(), 'project-env-'));
	writeFileSync(join(root, '.env'), 'API_TARGET=http://racine\nBASE_PATH=/b\n');
	return root;
}

describe('loadProjectEnv', () => {
	it('lit seulement le .env racine sans instance', () => {
		expect(loadProjectEnv({}, project())).toEqual({ API_TARGET: 'http://racine', BASE_PATH: '/b' });
	});

	it("fait primer le fichier de l'instance sur le .env racine", () => {
		const root = project();
		mkdirSync(join(root, 'instances', 'lorraine'), { recursive: true });
		writeFileSync(join(root, 'instances', 'lorraine', 'instance.env'), 'API_TARGET=http://lorraine\n');

		expect(loadProjectEnv({ BIBLIO_INSTANCE: 'lorraine' }, root)).toEqual({
			API_TARGET: 'http://lorraine',
			BASE_PATH: '/b'
		});
	});

	it("échoue si le fichier de l'instance manque", () => {
		expect(() => loadProjectEnv({ BIBLIO_INSTANCE: 'nantes' }, project())).toThrow(
			join('instances', 'nantes', 'instance.env')
		);
	});
});
