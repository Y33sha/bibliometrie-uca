/** Segment d'un texte : `match` vrai pour une occurrence du terme cherché. */
export interface HighlightSegment {
	text: string;
	match: boolean;
}

// Caractère sans accent ni casse. Chaque caractère est normalisé seul : le texte normalisé garde la longueur du texte d'origine, et les positions se correspondent.
function fold(char: string): string {
	const base = char.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
	return base.length === 1 ? base : char.toLowerCase();
}

/** Découpe `text` autour des occurrences de `term`, sans tenir compte des accents ni de la casse. Un terme vide renvoie le texte entier. */
export function highlight(text: string, term: string): HighlightSegment[] {
	const needle = Array.from(term.trim()).map(fold).join('');
	if (!needle) return [{ text, match: false }];
	const chars = Array.from(text);
	const haystack = chars.map(fold).join('');
	const segments: HighlightSegment[] = [];
	let from = 0;
	for (let at = haystack.indexOf(needle); at !== -1; at = haystack.indexOf(needle, at + needle.length)) {
		if (at > from) segments.push({ text: chars.slice(from, at).join(''), match: false });
		segments.push({ text: chars.slice(at, at + needle.length).join(''), match: true });
		from = at + needle.length;
	}
	if (from < chars.length) segments.push({ text: chars.slice(from).join(''), match: false });
	return segments;
}
