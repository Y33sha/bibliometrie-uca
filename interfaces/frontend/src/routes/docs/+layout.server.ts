import { NAV, isSection } from '$lib/docs/pages';
import { readDocFile, extractFirstH1, listSectionSlugs } from '$lib/docs/filesystem.server';
import type { LayoutServerLoad } from './$types';

export type NavItem =
	| { kind: 'page'; slug: string; title: string }
	| {
			kind: 'section';
			section: string;
			title: string;
			children: { slug: string; title: string }[];
	  };

function pageEntry(slug: string): { slug: string; title: string } {
	const content = readDocFile(slug);
	return { slug, title: extractFirstH1(content) || slug };
}

export const load: LayoutServerLoad = async () => {
	const nav: NavItem[] = NAV.map((node) => {
		if (isSection(node)) {
			return {
				kind: 'section',
				section: node.section,
				title: node.title,
				children: listSectionSlugs(node.section).map(pageEntry)
			};
		}
		return { kind: 'page', ...pageEntry(node.slug) };
	});
	return { nav };
};
