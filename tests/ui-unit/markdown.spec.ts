import { describe, expect, it, vi } from 'vitest';

import { renderMarkdown } from '../../src/andromeda/static/ts/index/markdown.ts';

describe('renderMarkdown', () => {
  it('renders headings and paragraphs', () => {
    const html = renderMarkdown('# Title\n\nA paragraph line.');

    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<p>A paragraph line.</p>');
  });

  it('renders inline emphasis, strong, and code spans', () => {
    const html = renderMarkdown('Use *emphasis*, **strong**, and `code`.');

    expect(html).toContain('<em>emphasis</em>');
    expect(html).toContain('<strong>strong</strong>');
    expect(html).toContain('<code>code</code>');
  });

  it('sanitizes unsafe markdown links', () => {
    const html = renderMarkdown('[bad](javascript:alert(1)) and [ok](https://example.com)');

    expect(html).toContain('<a href="#" target="_blank" rel="noopener">bad</a>');
    expect(html).toContain('<a href="https://example.com" target="_blank" rel="noopener">ok</a>');
  });

  it('renders bullet lists and closes list before next paragraph', () => {
    const html = renderMarkdown('- one\n- two\n\nafter list');

    expect(html).toContain('<ul><li>one</li><li>two</li></ul>');
    expect(html).toContain('<p>after list</p>');
  });

  it('renders fenced code blocks and escapes HTML in code content', () => {
    const html = renderMarkdown('```\nif (a < b) return true;\n```');

    expect(html).toContain('<pre><code>if (a &lt; b) return true;\n</code></pre>');
  });

  it('renders markdown tables with alignment hints', () => {
    const md = ['| name | value |', '| :--- | ---: |', '| acme | 10 |'].join('\n');
    const html = renderMarkdown(md);

    expect(html).toContain('<div class="tableWrap"><table><thead><tr>');
    expect(html).toContain('<th style="text-align:left">name</th>');
    expect(html).toContain('<th style="text-align:right">value</th>');
    expect(html).toContain('<td style="text-align:left">acme</td>');
    expect(html).toContain('<td style="text-align:right">10</td>');
  });

  it('renders thematic breaks for --- *** and ___', () => {
    const html = renderMarkdown('a\n---\nb\n***\nc\n___\nd');

    const hrCount = (html.match(/<hr \/>/g) || []).length;
    expect(hrCount).toBe(3);
  });

  it('emits line breaks for blank lines outside special blocks', () => {
    const html = renderMarkdown('line1\n\nline2');

    expect(html).toContain('<p>line1</p><br /><p>line2</p>');
  });

  it('calls citation linker with enable=true when citations are enabled', () => {
    const linker = vi.fn((input: string, opts: { enable: boolean }) => {
      if (!opts.enable) return input;
      return input.replace('[doc=abc chunk=ch1]', '<a class="citationLink">cite</a>');
    });

    const html = renderMarkdown('claim [doc=abc chunk=ch1]', {
      citations: true,
      linkifyDocCitations: linker,
    });

    expect(linker).toHaveBeenCalledTimes(1);
    expect(linker).toHaveBeenCalledWith(expect.any(String), { enable: true });
    expect(html).toContain('<a class="citationLink">cite</a>');
  });

  it('calls citation linker with enable=false when citations are disabled', () => {
    const linker = vi.fn((input: string) => input);

    renderMarkdown('claim [doc=abc]', {
      citations: false,
      linkifyDocCitations: linker,
    });

    expect(linker).toHaveBeenCalledTimes(1);
    expect(linker).toHaveBeenCalledWith(expect.any(String), { enable: false });
  });
});
