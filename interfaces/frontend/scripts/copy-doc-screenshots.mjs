// Copie `docs/screenshots/` (source unique, lisible sur GitHub) vers
// `interfaces/frontend/static/docs-screenshots/` (servi par SvelteKit
// sous `/<base>/docs-screenshots/`). Lancé en `predev` et `prebuild`.
// La destination est nettoyée à chaque exécution pour propager les
// suppressions côté source.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, '../../../docs/screenshots');
const DEST = path.resolve(__dirname, '../static/docs-screenshots');

async function main() {
	try {
		await fs.access(SRC);
	} catch {
		console.warn(`[copy-doc-screenshots] ${SRC} introuvable, rien à copier.`);
		return;
	}
	await fs.rm(DEST, { recursive: true, force: true });
	await fs.cp(SRC, DEST, { recursive: true });
	const files = await fs.readdir(DEST);
	console.log(`[copy-doc-screenshots] ${files.length} fichier(s) copié(s) vers static/docs-screenshots/`);
}

main().catch((err) => {
	console.error('[copy-doc-screenshots] échec :', err);
	process.exit(1);
});
