export type FlatPage = { slug: string };
export type Section = { section: string; title: string };

export type NavNode = FlatPage | Section;

export function isSection(node: NavNode): node is Section {
	return 'section' in node;
}

/**
 * Structure ordonnée de la documentation.
 *
 * - Un `FlatPage` correspond à un `.md` à plat (slug = nom de fichier sans extension).
 * - Une `Section` correspond à un dossier (`docs/<section>/`) qui contient
 *   plusieurs `.md` préfixés `NN-`. Le titre s'affiche comme en-tête non
 *   cliquable dans la sidebar, et le filesystem fournit la liste ordonnée
 *   des enfants à partir du dossier.
 */
export const NAV: NavNode[] = [
	{ slug: 'architecture' },
	{ slug: 'donnees' },
	{ section: 'sources', title: 'Sources de données' },
	{ slug: 'pipeline' },
	{ slug: 'exploitation' },
	{ slug: 'guide-utilisateur' },
	{ slug: 'glossaire' }
];
