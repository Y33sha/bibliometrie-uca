import { error, redirect } from '@sveltejs/kit';
import { base } from '$app/paths';
import { parseMarkdown } from '$lib/docs/parser';
import { readDocFile, hasDocFile, listSectionSlugs } from '$lib/docs/filesystem.server';
import { NAV, isSection } from '$lib/docs/pages';
import type { PageServerLoad, EntryGenerator } from './$types';

export const prerender = true;

export const entries: EntryGenerator = () => {
	const slugs: string[] = [];
	for (const node of NAV) {
		if (isSection(node)) {
			// Le slug nu de la section (ex. `donnees`) est prérendu comme redirection
			// vers son premier enfant, pour que les liens vers l'index d'un dossier
			// (`[…](../donnees/)`) résolvent, comme sur GitHub.
			slugs.push(node.section);
			for (const childSlug of listSectionSlugs(node.section)) slugs.push(childSlug);
		} else {
			slugs.push(node.slug);
		}
	}
	return slugs.map((slug) => ({ slug }));
};

export const load: PageServerLoad = async ({ params }) => {
	const slug = params.slug;
	if (!hasDocFile(slug)) {
		// Slug d'une section (dossier) : rediriger vers son premier enfant.
		const children = listSectionSlugs(slug);
		if (children.length > 0) {
			throw redirect(307, `${base}/docs/${children[0]}`);
		}
		throw error(404, `Document '${slug}' introuvable`);
	}
	const content = readDocFile(slug);
	const { html, toc, title } = parseMarkdown(content, base, slug);
	return { html, toc, title };
};
