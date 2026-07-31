import { put } from './client';
import type { components } from './schema';

type ConfigItem = components['schemas']['ConfigItem'];

export function setValue(key: string, value: unknown): Promise<ConfigItem> {
	return put<ConfigItem>(`/api/config/${key}`, { value });
}
