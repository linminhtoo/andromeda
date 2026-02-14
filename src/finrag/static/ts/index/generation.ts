export type GenerationInputs = {
  topKRetrieve: HTMLInputElement;
  topKRerank: HTMLInputElement;
  draftMaxTokens: HTMLInputElement;
  finalMaxTokens: HTMLInputElement;
};

/** Manage generation mode presets and map them into UI control values. */
export class GenerationModeManager {
  private defaultMode = 'normal';
  private presets: any[] = [];
  private presetByKey = new Map<string, any>();

  /** Return the configured default generation mode key. */
  getDefaultMode(): string {
    return this.defaultMode;
  }

  /** Check whether a mode key exists in currently loaded presets. */
  hasMode(mode: string): boolean {
    return this.presetByKey.has(String(mode || '').trim().toLowerCase());
  }

  /** Load mode metadata from API response payload. */
  setFromPayload(payload: any): void {
    const rawPresets = Array.isArray(payload?.presets) ? payload.presets : [];
    this.defaultMode = String(payload?.default_mode || 'normal').trim().toLowerCase() || 'normal';
    this.presets = rawPresets.filter((p) => p && typeof p === 'object' && p.key);
    this.presetByKey = new Map(this.presets.map((p) => [String(p.key).toLowerCase(), p]));
  }

  /** Fetch generation presets from backend, with static fallback defaults. */
  async loadFromServer(): Promise<void> {
    try {
      const res = await fetch('/generation_presets');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      this.setFromPayload(data);
    } catch {
      this.setFromPayload({
        default_mode: 'normal',
        presets: [
          {
            key: 'quick',
            label: 'Quick',
            description: 'Fast + concise. Skips reranking and verification.',
            top_k_retrieve: 12,
            top_k_rerank: 6,
            draft_max_tokens: 16384,
            final_max_tokens: 16384,
          },
          {
            key: 'normal',
            label: 'Normal',
            description: 'Balanced quality/speed. Uses reranking + verification.',
            top_k_retrieve: 30,
            top_k_rerank: 8,
            draft_max_tokens: 65536,
            final_max_tokens: 32768,
          },
          {
            key: 'thinking',
            label: 'Thinking',
            description: 'Higher recall + deeper report. Retrieves/reranks more and verifies.',
            top_k_retrieve: 40,
            top_k_rerank: 12,
            draft_max_tokens: 65536,
            final_max_tokens: 45000,
          },
        ],
      });
    }
  }

  /** Populate mode `<select>` options from loaded presets. */
  populateSelect(selectEl: HTMLSelectElement): void {
    selectEl.innerHTML = '';
    this.presets.forEach((preset) => {
      const opt = document.createElement('option');
      opt.value = String(preset.key || '');
      opt.textContent = String(preset.label || preset.key || '');
      selectEl.appendChild(opt);
    });
  }

  /** Render help text for the active mode in the UI. */
  updateModeHelp(mode: string, helpEl: HTMLElement): void {
    const preset = this.presetByKey.get(String(mode || '').toLowerCase());
    if (!preset) {
      helpEl.textContent = '';
      helpEl.style.display = 'none';
      return;
    }
    const description = String(preset.description || '').trim();
    helpEl.textContent = description;
    helpEl.style.display = description ? 'block' : 'none';
  }

  /** Apply preset values into advanced controls for the selected mode. */
  applyModePreset(mode: string, inputs: GenerationInputs, { overwriteAdvanced = true }: { overwriteAdvanced?: boolean } = {}): void {
    const preset = this.presetByKey.get(String(mode || '').toLowerCase());
    if (!preset) return;
    if (overwriteAdvanced) {
      if (preset.top_k_retrieve) inputs.topKRetrieve.value = preset.top_k_retrieve;
      if (preset.top_k_rerank) inputs.topKRerank.value = preset.top_k_rerank;
      if (preset.draft_max_tokens) inputs.draftMaxTokens.value = preset.draft_max_tokens;
      if (preset.final_max_tokens) inputs.finalMaxTokens.value = preset.final_max_tokens;
    }
  }
}
