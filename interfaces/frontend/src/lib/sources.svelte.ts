// Sources bibliographiques : libellés et ordre d'affichage servis par l'API, logos locaux.
import { base } from '$app/paths';
import { api } from '$lib/api';
import type { components } from '$lib/api/schema';

type EnumOption = components['schemas']['EnumOption'];

/** Logo local de chaque source : l'appli doit tourner hors ligne (pas de logo distant). */
const ICONS: Record<string, string> = {
	hal: `${base}/icons/hal.ico`,
	openalex: `${base}/icons/openalex.png`,
	scanr: `${base}/scanr-icon.svg`,
	wos: `${base}/icons/wos.ico`,
	theses: `${base}/icons/theses.ico`,
	crossref: `${base}/icons/crossref.ico`,
	datacite: `${base}/icons/datacite.ico`
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
