import { base } from '$app/paths';

export async function api<T>(url: string): Promise<T> {
	const res = await fetch(base + url);
	if (!res.ok) throw new Error(`API error ${res.status}`);
	return res.json();
}
