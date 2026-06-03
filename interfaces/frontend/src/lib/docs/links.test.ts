import { describe, it, expect } from 'vitest';
import { resolveDocLink } from './links';

const BASE = '/bibliometrie';

describe('resolveDocLink — depuis une page racine', () => {
	const FROM = 'architecture';

	it('préfixe un slug nu par /docs/', () => {
		expect(resolveDocLink('pipeline', BASE, FROM)).toBe('/bibliometrie/docs/pipeline');
	});

	it('conserve une ancre interne au slug', () => {
		expect(resolveDocLink('glossaire#ror', BASE, FROM)).toBe('/bibliometrie/docs/glossaire#ror');
	});

	it('strippe une extension .md finale', () => {
		expect(resolveDocLink('pipeline.md', BASE, FROM)).toBe('/bibliometrie/docs/pipeline');
	});

	it('strippe .md devant une ancre', () => {
		expect(resolveDocLink('pipeline.md#section', BASE, FROM)).toBe(
			'/bibliometrie/docs/pipeline#section'
		);
	});

	it('laisse les URLs externes inchangées', () => {
		expect(resolveDocLink('https://ror.org/01a8ajp46', BASE, FROM)).toBe(
			'https://ror.org/01a8ajp46'
		);
	});

	it('laisse les liens absolus inchangés', () => {
		expect(resolveDocLink('/some/path', BASE, FROM)).toBe('/some/path');
	});

	it('laisse les ancres pures inchangées', () => {
		expect(resolveDocLink('#persons', BASE, FROM)).toBe('#persons');
	});

	it('laisse les mailto: inchangés', () => {
		expect(resolveDocLink('mailto:foo@bar', BASE, FROM)).toBe('mailto:foo@bar');
	});

	it('résout un chemin imbriqué vers une section', () => {
		expect(resolveDocLink('sources/imports-manuels#donnees-rh', BASE, FROM)).toBe(
			'/bibliometrie/docs/sources/imports-manuels#donnees-rh'
		);
	});
});

describe('resolveDocLink — depuis une page de section', () => {
	const FROM = 'sources/vue-d-ensemble';

	it("remonte d'un niveau avec ../ vers une page racine", () => {
		expect(resolveDocLink('../guide-utilisateur#problemes-hal', BASE, FROM)).toBe(
			'/bibliometrie/docs/guide-utilisateur#problemes-hal'
		);
	});

	it('résout un lien nu comme intra-section', () => {
		expect(resolveDocLink('hal', BASE, FROM)).toBe('/bibliometrie/docs/sources/hal');
	});

	it('résout ./ comme intra-section', () => {
		expect(resolveDocLink('./openalex', BASE, FROM)).toBe(
			'/bibliometrie/docs/sources/openalex'
		);
	});
});

describe('resolveDocLink — liens vers le code source (sortie de docs/)', () => {
	const REPO = 'https://github.com/Y33sha/bibliometrie-uca/blob/master';

	it('réécrit un lien fichier qui sort de docs/ vers GitHub', () => {
		expect(
			resolveDocLink('../../domain/publications/deduplication.py', BASE, 'playbooks/dedup')
		).toBe(`${REPO}/domain/publications/deduplication.py`);
	});

	it('réécrit un lien dossier qui sort de docs/ vers GitHub', () => {
		expect(resolveDocLink('../../infrastructure/raw_store/', BASE, 'pipeline/normalize')).toBe(
			`${REPO}/infrastructure/raw_store`
		);
	});

	it('conserve les préfixes NN- et extensions du chemin source', () => {
		expect(
			resolveDocLink(
				'../../alembic/versions/2026_05_24_2030-b9a2c8d4e7f1_x.py',
				BASE,
				'playbooks/dedup'
			)
		).toBe(`${REPO}/alembic/versions/2026_05_24_2030-b9a2c8d4e7f1_x.py`);
	});

	it('reste interne tant que le lien ne sort pas de docs/', () => {
		expect(resolveDocLink('../guide-utilisateur', BASE, 'sources/hal')).toBe(
			'/bibliometrie/docs/guide-utilisateur'
		);
	});
});
