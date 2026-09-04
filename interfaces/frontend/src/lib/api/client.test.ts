/* Client HTTP de l'interface.
 *
 * Les lectures s'annulent par clé : une requête portant une clé déjà en vol interrompt la
 * précédente, et la requête interrompue reste en suspens plutôt que de rendre la main. Les
 * écritures traduisent un statut d'échec en `ApiError` et rendent `null` sur une réponse sans
 * corps.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiError, api, post, put, patch, del } from './client';

type RequeteEnVol = {
	url: string;
	init: RequestInit | undefined;
	resoudre: (reponse: Response) => void;
};

let enVol: RequeteEnVol[] = [];

beforeEach(() => {
	enVol = [];
	vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
		return new Promise<Response>((resoudre, rejeter) => {
			enVol.push({ url, init, resoudre });
			init?.signal?.addEventListener('abort', () => {
				rejeter(new DOMException('Requête interrompue', 'AbortError'));
			});
		});
	});
});

afterEach(() => {
	vi.unstubAllGlobals();
});

function reponseJson(corps: unknown, statut = 200): Response {
	return new Response(JSON.stringify(corps), {
		status: statut,
		headers: { 'Content-Type': 'application/json' }
	});
}

/** Laisse les tâches en attente s'exécuter avant l'assertion qui suit. */
function toursDeBoucle(): Promise<void> {
	return new Promise((resoudre) => setTimeout(resoudre, 0));
}

/** Rend `'en suspens'` quand la promesse ne se règle pas dans le délai imparti. */
function reglementOuSuspens<T>(promesse: Promise<T>): Promise<T | 'en suspens'> {
	return Promise.race([
		promesse,
		new Promise<'en suspens'>((resoudre) => setTimeout(() => resoudre('en suspens'), 30))
	]);
}

describe('ApiError', () => {
	it('donne le message que porte le corps de la réponse', () => {
		const erreur = new ApiError(422, { detail: 'Identifiant inconnu' });
		expect(erreur.detailMessage).toBe('Identifiant inconnu');
	});

	it('rend null quand le detail n’est pas une chaîne', () => {
		const erreur = new ApiError(422, { detail: [{ msg: 'champ manquant' }] });
		expect(erreur.detailMessage).toBeNull();
	});

	it('rend null quand la réponse ne porte pas de corps exploitable', () => {
		expect(new ApiError(500, null).detailMessage).toBeNull();
	});

	it('porte le statut de la réponse', () => {
		expect(new ApiError(404, null).status).toBe(404);
	});
});

describe('lecture', () => {
	it('rend le corps JSON d’une réponse aboutie', async () => {
		const promesse = api<{ total: number }>('/api/publications');
		await toursDeBoucle();
		enVol[0].resoudre(reponseJson({ total: 3 }));
		expect(await promesse).toEqual({ total: 3 });
	});

	it('vise l’adresse demandée', async () => {
		void api('/api/publications');
		await toursDeBoucle();
		expect(enVol[0].url).toContain('/api/publications');
	});

	it('lève une ApiError portant le statut et le corps sur une réponse en échec', async () => {
		const promesse = api('/api/publications').catch((e: unknown) => e);
		await toursDeBoucle();
		enVol[0].resoudre(reponseJson({ detail: 'Pas trouvé' }, 404));
		const erreur = await promesse;
		expect(erreur).toBeInstanceOf(ApiError);
		expect((erreur as ApiError).status).toBe(404);
		expect((erreur as ApiError).detailMessage).toBe('Pas trouvé');
	});

	it('reprend le corps en texte quand la réponse en échec n’est pas du JSON', async () => {
		const promesse = api('/api/publications').catch((e: unknown) => e);
		await toursDeBoucle();
		enVol[0].resoudre(new Response('502 Bad Gateway', { status: 502 }));
		const erreur = await promesse;
		expect(erreur).toBeInstanceOf(ApiError);
		expect((erreur as ApiError).detail).toBe('502 Bad Gateway');
	});
});

describe('annulation par clé', () => {
	it('interrompt la requête précédente portant la même clé', async () => {
		void api('/api/publications?page=1', { key: 'liste' });
		await toursDeBoucle();
		void api('/api/publications?page=2', { key: 'liste' });
		await toursDeBoucle();
		expect(enVol[0].init?.signal?.aborted).toBe(true);
		expect(enVol[1].init?.signal?.aborted).toBe(false);
	});

	it('laisse la requête interrompue en suspens, sans résolution ni rejet', async () => {
		const premiere = api('/api/publications?page=1', { key: 'liste' });
		await toursDeBoucle();
		void api('/api/publications?page=2', { key: 'liste' });
		expect(await reglementOuSuspens(premiere)).toBe('en suspens');
	});

	it('laisse coexister deux clés distinctes', async () => {
		void api('/api/publications', { key: 'liste' });
		await toursDeBoucle();
		void api('/api/stats', { key: 'statistiques' });
		await toursDeBoucle();
		expect(enVol[0].init?.signal?.aborted).toBe(false);
		expect(enVol[1].init?.signal?.aborted).toBe(false);
	});

	it('interrompt encore la requête en vol après qu’une plus ancienne a été interrompue', async () => {
		void api('/api/publications?page=1', { key: 'liste' });
		await toursDeBoucle();
		void api('/api/publications?page=2', { key: 'liste' });
		await toursDeBoucle();
		void api('/api/publications?page=3', { key: 'liste' });
		await toursDeBoucle();
		// La sortie de la première requête ne retire pas le contrôleur de la deuxième, qui reste
		// donc interruptible par la troisième.
		expect(enVol[1].init?.signal?.aborted).toBe(true);
		expect(enVol[2].init?.signal?.aborted).toBe(false);
	});

	it('sert une requête portant une clé dont la précédente a abouti', async () => {
		const premiere = api<{ page: number }>('/api/publications?page=1', { key: 'liste' });
		await toursDeBoucle();
		enVol[0].resoudre(reponseJson({ page: 1 }));
		expect(await premiere).toEqual({ page: 1 });

		const seconde = api<{ page: number }>('/api/publications?page=2', { key: 'liste' });
		await toursDeBoucle();
		enVol[1].resoudre(reponseJson({ page: 2 }));
		expect(await seconde).toEqual({ page: 2 });
	});
});

describe('écriture', () => {
	it('annonce le type de contenu et sérialise le corps', async () => {
		void post('/api/persons', { name: 'Curie' });
		await toursDeBoucle();
		expect(enVol[0].init?.method).toBe('POST');
		expect(enVol[0].init?.headers).toEqual({ 'Content-Type': 'application/json' });
		expect(enVol[0].init?.body).toBe(JSON.stringify({ name: 'Curie' }));
	});

	it('n’annonce pas de type de contenu quand la requête ne porte pas de corps', async () => {
		void del('/api/persons/1');
		await toursDeBoucle();
		expect(enVol[0].init?.method).toBe('DELETE');
		expect(enVol[0].init?.headers).toBeUndefined();
		expect(enVol[0].init?.body).toBeUndefined();
	});

	it('transmet la méthode de chaque écriture', async () => {
		void put('/api/persons/1', {});
		await toursDeBoucle();
		void patch('/api/persons/1', {});
		await toursDeBoucle();
		expect(enVol[0].init?.method).toBe('PUT');
		expect(enVol[1].init?.method).toBe('PATCH');
	});

	it('rend null sur une réponse sans contenu', async () => {
		const promesse = del('/api/persons/1');
		await toursDeBoucle();
		enVol[0].resoudre(new Response(null, { status: 204 }));
		expect(await promesse).toBeNull();
	});

	it('rend null sur une réponse aboutie au corps vide', async () => {
		const promesse = post('/api/persons', {});
		await toursDeBoucle();
		enVol[0].resoudre(new Response('', { status: 200 }));
		expect(await promesse).toBeNull();
	});

	it('rend le corps JSON d’une écriture aboutie', async () => {
		const promesse = post<{ id: number }>('/api/persons', { name: 'Curie' });
		await toursDeBoucle();
		enVol[0].resoudre(reponseJson({ id: 7 }, 201));
		expect(await promesse).toEqual({ id: 7 });
	});

	it('lève une ApiError sur une écriture refusée', async () => {
		const promesse = post('/api/persons', {}).catch((e: unknown) => e);
		await toursDeBoucle();
		enVol[0].resoudre(reponseJson({ detail: 'Doublon' }, 409));
		const erreur = await promesse;
		expect(erreur).toBeInstanceOf(ApiError);
		expect((erreur as ApiError).status).toBe(409);
		expect((erreur as ApiError).detailMessage).toBe('Doublon');
	});
});
