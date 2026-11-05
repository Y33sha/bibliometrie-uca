// Sources bibliographiques : libellés et ordre d'affichage servis par l'API, logos locaux.
import { asset } from '$app/paths';
import { api } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';

type EnumOption = components['schemas']['EnumOption'];

/** Logo local de chaque source : l'appli doit tourner hors ligne (pas de logo distant). */
const ICONS: Record<string, string> = {
	hal: asset('icons/hal.ico'),
	openalex: asset('icons/openalex.png'),
	scanr: asset('scanr-icon.svg'),
	wos: asset('icons/wos.ico'),
	theses: asset('icons/theses.ico'),
	crossref: asset('icons/crossref.ico'),
	datacite: asset('icons/datacite.ico')
};

const sources = $state({ order: [] as string[], labels: {} as Record<string, string> });

let loading: Promise<void> | null = null;

/** Charge les sources une seule fois. Un échec laisse les clés brutes à l'affichage, et l'appel suivant réessaie. */
export function loadSources(): Promise<void> {
	loading ??= api<EnumOption[]>('/api/sources')
		.then((options) => {
			sources.order = options.map((o) => o.value);
			sources.labels = Object.fromEntries(options.map((o) => [o.value, o.label_fr]));
		})
		.catch(() => {
			loading = null;
		});
	return loading;
}

/** Libellé d'une source (avec repli sur la clé brute tant que les sources ne sont pas chargées, ou pour une source inconnue). */
export function sourceLabel(source: string): string {
	return sources.labels[source] ?? source;
}

/** Sources dans l'ordre d'affichage. */
export function sourceOrder(): string[] {
	return sources.order;
}

/** Chemin du logo local d'une source (`undefined` si aucun). */
export function sourceIcon(source: string): string | undefined {
	return ICONS[source];
}

/** Rapport de participation d'un membre Crossref : le compte sous lequel un éditeur dépose ses DOI. */
export function crossrefMemberUrl(memberId: number): string {
	return `https://www.crossref.org/members/prep/${memberId}`;
}

/** Membres Crossref distincts d'un éditeur, tirés de ses préfixes DOI, dans l'ordre de ses préfixes. */
export function crossrefMemberIds(doiPrefixes: { crossref_member_id?: number | null }[]): number[] {
	const members = doiPrefixes.map((p) => p.crossref_member_id).filter((m) => m != null);
	return [...new Set(members)];
}
