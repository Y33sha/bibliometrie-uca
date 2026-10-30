// Session de l'utilisateur : login et rôles, lus par `/api/auth/check`.
import { resolve } from '$app/paths';
import { auth } from '#lib/api/index.js';

export const session = $state({ loaded: false, login: null as string | null, roles: [] as string[] });

let loading: Promise<void> | null = null;

// Le navigateur garde le rôle admin de la dernière session lue, d'un onglet à l'autre.
const ADMIN_STORAGE_KEY = 'session-admin';

function readStoredAdmin(): boolean {
	try {
		return localStorage.getItem(ADMIN_STORAGE_KEY) === '1';
	} catch {
		return false;
	}
}

function storeAdmin(): void {
	try {
		localStorage.setItem(ADMIN_STORAGE_KEY, isAdmin() ? '1' : '0');
	} catch {
		// Stockage inaccessible : la barre de navigation prend l'aspect admin à la lecture de la session.
	}
}

const storedAdmin = readStoredAdmin();

/** Lit la session une seule fois ; `refresh` force une nouvelle lecture, après une connexion ou une déconnexion. Un échec vaut une session anonyme, et l'appel suivant réessaie. */
export function loadSession(refresh = false): Promise<void> {
	if (refresh) loading = null;
	loading ??= auth
		.check()
		.then((data) => {
			session.login = data.authenticated ? (data.login ?? null) : null;
			session.roles = data.authenticated ? data.roles : [];
		})
		.catch(() => {
			session.login = null;
			session.roles = [];
			loading = null;
		})
		.finally(() => {
			session.loaded = true;
			storeAdmin();
		});
	return loading;
}

/** L'utilisateur de la session a le rôle admin. */
export function isAdmin(): boolean {
	return session.roles.includes('admin');
}

/** La barre de navigation prend l'aspect admin : rôle de la session, ou de la dernière session lue tant que la session courante n'est pas lue. */
export function adminLook(): boolean {
	return session.loaded ? isAdmin() : storedAdmin;
}

/** Page de connexion, qui ramène à `returnTo` (chemin et paramètres de l'URL courante) une fois connecté. */
export function loginUrl(returnTo: Pick<URL, 'pathname' | 'search'>): string {
	return `${resolve('login')}?redirect=${encodeURIComponent(returnTo.pathname + returnTo.search)}`;
}

/** Chemin de retour après connexion : `redirect` s'il désigne une page du site, la page Statistiques sinon. */
export function returnPath(redirect: string | null, origin: string): string {
	if (redirect) {
		const target = new URL(redirect, origin);
		if (target.origin === origin && target.pathname.startsWith(resolve(''))) {
			return target.pathname + target.search;
		}
	}
	return resolve('stats');
}
