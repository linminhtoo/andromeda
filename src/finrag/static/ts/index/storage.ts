import { LS_HISTORY, LS_SETTINGS, LS_UI } from './dom.js';
import { readJsonStorage, writeJsonStorage } from '../shared/storage.js';

/** Return cached query history from browser storage. */
export function readLocalHistory(): any[] {
  const value = readJsonStorage<any>(LS_HISTORY, []);
  return Array.isArray(value) ? value : [];
}

/** Persist query history cache in browser storage. */
export function writeLocalHistory(items: any[]): void {
  writeJsonStorage(LS_HISTORY, Array.isArray(items) ? items : []);
}

/** Read saved generation settings from browser storage. */
export function readSettings(): any | null {
  const value = readJsonStorage<any>(LS_SETTINGS, null);
  if (value && typeof value === 'object') return value;
  return null;
}

/** Persist generation settings in browser storage. */
export function writeSettings(settings: any): void {
  writeJsonStorage(LS_SETTINGS, settings || {});
}

/** Read persisted UI layout preferences from browser storage. */
export function readUi(): any | null {
  const value = readJsonStorage<any>(LS_UI, null);
  if (value && typeof value === 'object') return value;
  return null;
}

/** Merge and persist UI layout preferences. */
export function writeUi(patch: any): void {
  const prev = readUi() || {};
  const next = { ...prev, ...(patch || {}) };
  writeJsonStorage(LS_UI, next);
}
