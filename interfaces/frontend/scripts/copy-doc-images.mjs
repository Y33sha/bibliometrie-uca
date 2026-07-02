// Copie les images de doc (source unique, lisibles sur GitHub) vers
// `interfaces/frontend/static/`, servies par SvelteKit sous `/<base>/docs-<dossier>/`.
// Deux sources : `docs/img/` (captures et illustrations) et `docs/graphs/`
// (diagrammes générés ; seules les images sont copiées, la source du générateur
// reste côté `docs/graphs/`). Lancé en `predev` et `prebuild`. Chaque destination
// est nettoyée à chaque exécution pour propager les suppressions côté source.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const IMAGE_EXT = new Set(['.png', '.svg', '.jpg', '.jpeg', '.gif', '.webp']);

// `dossier docs` -> `dossier static servi`.
const FOLDERS = [
	{ src: '../../../docs/img', dest: '../static/docs-img' },
	{ src: '../../../docs/graphs', dest: '../static/docs-graphs' }
];

async function copyImages(srcRel, destRel) {
	const src = path.resolve(__dirname, srcRel);
	const dest = path.resolve(__dirname, destRel);
	try {
		await fs.access(src);
	} catch {
		console.warn(`[copy-doc-images] ${src} introuvable, ignoré.`);
		return 0;
	}
	await fs.rm(dest, { recursive: true, force: true });
	await fs.mkdir(dest, { recursive: true });
	const entries = await fs.readdir(src, { withFileTypes: true });
	let n = 0;
	for (const entry of entries) {
		if (!entry.isFile() || !IMAGE_EXT.has(path.extname(entry.name).toLowerCase())) continue;
		await fs.cp(path.join(src, entry.name), path.join(dest, entry.name));
		n += 1;
	}
	return n;
}

async function main() {
	for (const { src, dest } of FOLDERS) {
		const n = await copyImages(src, dest);
		console.log(`[copy-doc-images] ${n} image(s) copiée(s) vers ${dest.split('/static/')[1] ?? dest}`);
	}
}

main().catch((err) => {
	console.error('[copy-doc-images] échec :', err);
	process.exit(1);
});
