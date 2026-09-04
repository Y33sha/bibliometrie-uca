/* Traduction des échecs de connexion en messages.
 *
 * Un même message pour tous les statuts masque la cause : un proxy mal ciblé ou un serveur en erreur se lisent alors comme un mot de passe refusé, et la recherche part du mauvais côté. Chaque statut garde donc sa formulation.
 */

import { describe, it, expect } from 'vitest';
import { ApiError } from './client';
import { loginErrorMessage } from './auth';

describe('loginErrorMessage', () => {
	it('désigne les identifiants sur un refus d’authentification', () => {
		const message = loginErrorMessage(new ApiError(401, { detail: 'Identifiants incorrects' }));
		expect(message).toBe('Identifiants incorrects');
	});

	it('reprend le message du serveur sur un plafond de tentatives atteint', () => {
		const detail = 'Trop de tentatives de connexion. Réessayez plus tard.';
		expect(loginErrorMessage(new ApiError(429, { detail }))).toBe(detail);
	});

	it('annonce le plafond de tentatives même sans message exploitable du serveur', () => {
		expect(loginErrorMessage(new ApiError(429, null))).toMatch(/Trop de tentatives/);
	});

	it('donne le statut tel quel sur une réponse inattendue, sans parler d’identifiants', () => {
		const message = loginErrorMessage(new ApiError(404, { detail: 'Not Found' }));
		expect(message).toContain('404');
		expect(message).not.toMatch(/[Ii]dentifiants/);
	});

	it('distingue une erreur serveur d’un refus d’identifiants', () => {
		expect(loginErrorMessage(new ApiError(500, null))).not.toMatch(/[Ii]dentifiants/);
	});

	it('signale une panne de transport quand la requête n’a pas abouti', () => {
		expect(loginErrorMessage(new TypeError('Failed to fetch'))).toBe('Erreur de connexion');
	});
});
