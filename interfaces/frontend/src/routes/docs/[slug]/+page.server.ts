import { error } from '@sveltejs/kit';
import { base } from '$app/paths';
import { parseMarkdown } from '$lib/docs/parser';
import { readDocFile } from '$lib/docs/filesystem.server';
import { DOC_SLUGS } from '$lib/docs/pages';
import type { PageServerLoad, EntryGenerator } from './$types';

export const prerender = true;

export const entries: EntryGenerator = () => DOC_SLUGS.map((slug) => ({ slug }));

export const load: PageServerLoad = async ({ params }) => {
	const slug = params.slug;
	if (!(DOC_SLUGS as readonly string[]).includes(slug)) {
		throw error(404, `Document '${slug}' introuvable`);
	}
	const content = await readDocFile(slug);
	const { html, toc, title } = parseMarkdown(content, base);
	return { html, toc, title };
};
