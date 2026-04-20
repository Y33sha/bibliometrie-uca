import { put } from './client';

export function setValue(key: string, value: unknown): Promise<unknown> {
	return put(`/api/config/${key}`, { value });
}
