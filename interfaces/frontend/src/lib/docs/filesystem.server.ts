// Charge tous les .md de `docs/` au build via Vite.
// - Le contenu est embarqué dans le bundle serveur (`?raw`)
// - HMR automatique en dev quand un .md est édité
// - Pas de lecture filesystem au runtime
const rawDocs = import.meta.glob('../../../../../docs/*.md', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

const docsBySlug: Record<string, string> = Object.fromEntries(
	Object.entries(rawDocs).map(([filePath, content]) => {
		const slug = filePath.split('/').pop()!.replace(/\.md$/, '');
		return [slug, content];
	})
);

export function readDocFile(slug: string): string {
	const content = docsBySlug[slug];
	if (content === undefined) {
		throw new Error(`Document '${slug}' introuvable`);
	}
	return content;
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
