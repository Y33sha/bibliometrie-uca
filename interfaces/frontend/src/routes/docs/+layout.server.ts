import { DOC_SLUGS } from '$lib/docs/pages';
import { readDocFile, extractFirstH1 } from '$lib/docs/filesystem.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async () => {
	const pages = await Promise.all(
		DOC_SLUGS.map(async (slug) => {
			const content = await readDocFile(slug);
			return { slug, title: extractFirstH1(content) || slug };
		})
	);
	return { pages };
};
