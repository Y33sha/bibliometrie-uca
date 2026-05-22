// Charge tous les .md de `docs/` au build via Vite (récursif).
// - Le contenu est embarqué dans le bundle serveur (`?raw`)
// - HMR automatique en dev quand un .md est édité
// - Les `.md` sous `docs/chantiers/` sont exclus (fiches de chantier
//   non exposées en ligne)
const rawDocs = import.meta.glob('../../../../../docs/**/*.md', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

const DOCS_PREFIX_REGEX = /.*\/docs\//;
const NUMERIC_PREFIX_REGEX = /^\d+-/;

/**
 * Convertit un chemin de fichier (depuis Vite glob) en slug exposé :
 * - strippe le préfixe `.../docs/`
 * - strippe l'extension `.md`
 * - strippe les préfixes numériques `NN-` sur chaque segment de chemin
 *
 * Exemples :
 *   `.../docs/architecture.md`               → `architecture`
 *   `.../docs/sources/01-vue-d-ensemble.md`  → `sources/vue-d-ensemble`
 */
function pathToSlug(filePath: string): string {
	const relative = filePath.replace(DOCS_PREFIX_REGEX, '').replace(/\.md$/, '');
	return relative
		.split('/')
		.map((segment) => segment.replace(NUMERIC_PREFIX_REGEX, ''))
		.join('/');
}

const docsBySlug: Record<string, { content: string; filePath: string }> = {};
const slugsBySection: Record<string, string[]> = {};

for (const [filePath, content] of Object.entries(rawDocs)) {
	if (filePath.includes('/chantiers/')) continue;
	const slug = pathToSlug(filePath);
	docsBySlug[slug] = { content, filePath };

	// Si le slug est composé (contient un /), enregistrer comme enfant de section
	const slashIdx = slug.indexOf('/');
	if (slashIdx > 0) {
		const section = slug.slice(0, slashIdx);
		(slugsBySection[section] ??= []).push(slug);
	}
}

// Préserver l'ordre des sections : trier par filePath (qui contient le préfixe
// numérique NN-) pour que `01-foo` < `02-bar` < `10-baz`.
for (const section of Object.keys(slugsBySection)) {
	slugsBySection[section].sort((a, b) => {
		return docsBySlug[a].filePath.localeCompare(docsBySlug[b].filePath);
	});
}

export function readDocFile(slug: string): string {
	const entry = docsBySlug[slug];
	if (entry === undefined) {
		throw new Error(`Document '${slug}' introuvable`);
	}
	return entry.content;
}

export function hasDocFile(slug: string): boolean {
	return slug in docsBySlug;
}

/**
 * Retourne les slugs des `.md` d'une section, dans l'ordre des préfixes numériques.
 * Renvoie un tableau vide si la section n'existe pas (ou n'a pas de fichiers).
 */
export function listSectionSlugs(section: string): string[] {
	return slugsBySection[section] ?? [];
}

export function extractFirstH1(content: string): string {
	let inCodeBlock = false;
	for (const line of content.split(/\r?\n/)) {
		if (/^```/.test(line)) {
			inCodeBlock = !inCodeBlock;
			continue;
		}
		if (inCodeBlock) continue;
		const m = /^#\s+(.+)$/.exec(line);
		if (m) return m[1].trim();
	}
	return '';
}
