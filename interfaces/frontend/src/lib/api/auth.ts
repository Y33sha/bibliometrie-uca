import { ApiError, api, post } from './client';
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

/**
 * Message à afficher quand une tentative de connexion échoue.
 *
 * Chaque cause a sa formulation : confondre le refus d'identifiants avec une indisponibilité du serveur envoie chercher un mot de passe là où c'est la configuration ou le réseau qui est en cause. Un statut inattendu se dit tel quel, avec son code, plutôt que d'être rangé sous une explication qui n'a pas été vérifiée.
 */
export function loginErrorMessage(e: unknown): string {
	if (!(e instanceof ApiError)) return 'Erreur de connexion';
	if (e.status === 401) return 'Identifiants incorrects';
	if (e.status === 429) {
		return e.detailMessage ?? 'Trop de tentatives de connexion. Réessayez plus tard.';
	}
	return `Connexion impossible : le serveur a répondu ${e.status}.`;
}
