import { expect, test } from '@playwright/test';

type UiChunk = {
  chunk_id: string;
  doc_id: string;
  source: string;
  text: string;
  preview: string;
  score: number;
  headings: string[];
  metadata: {
    doc: {
      company: string;
      ticker: string;
      filing_type: string;
      filing_quarter: string;
      filing_date: string;
      period_end_date: string;
    };
    summary: string;
  };
};

const SOURCE_PATH = 'data/mock/acme_2025q4.md';

const SOURCE_TEXT = [
  '# ACME Q4 2025 Filing Notes',
  '',
  'Operating margin widened in Q4.',
  '',
  'Revenue grew 19% year over year due to datacenter demand.',
  '',
  '---',
  '',
  'Margin expanded too.',
].join('\n');

const CHUNKS: UiChunk[] = [
  {
    chunk_id: 'chunk-1',
    doc_id: 'doc-001',
    source: SOURCE_PATH,
    text: 'Operating margin widened in Q4.',
    preview: 'Operating margin widened in Q4.',
    score: 0.92,
    headings: ['Results', 'Margins'],
    metadata: {
      doc: {
        company: 'Acme Corp',
        ticker: 'ACME',
        filing_type: '10-Q',
        filing_quarter: '2025 Q4',
        filing_date: '2026-01-30',
        period_end_date: '2025-12-31',
      },
      summary: 'Quarterly margin trend discussion.',
    },
  },
  {
    chunk_id: 'chunk-2',
    doc_id: 'doc-001',
    source: SOURCE_PATH,
    text: 'Revenue grew 19% year over year due to datacenter demand.',
    preview: 'Revenue grew 19% year over year due to datacenter demand.',
    score: 0.96,
    headings: ['Results', 'Revenue'],
    metadata: {
      doc: {
        company: 'Acme Corp',
        ticker: 'ACME',
        filing_type: '10-Q',
        filing_quarter: '2025 Q4',
        filing_date: '2026-01-30',
        period_end_date: '2025-12-31',
      },
      summary: 'Revenue growth explanation.',
    },
  },
];

function toNdjson(events: object[]): string {
  return events.map((event) => JSON.stringify(event)).join('\n') + '\n';
}

async function mockBaseEndpoints(page: import('@playwright/test').Page): Promise<void> {
  await page.route('**/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok' }),
    });
  });

  await page.route('**/generation_presets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        default_mode: 'normal',
        presets: [
          {
            key: 'normal',
            label: 'Normal',
            description: 'Balanced quality/speed.',
            top_k_retrieve: 30,
            top_k_rerank: 8,
            draft_max_tokens: 65536,
            final_max_tokens: 32768,
            enable_rerank: true,
            enable_refine: false,
          },
        ],
      }),
    });
  });

  await page.route('**/history?*', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], path: 'history.jsonl' }),
    });
  });

  await page.route('**/ingested_companies', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{ ticker: 'ACME', company: 'Acme Corp' }],
        use_yahoo: false,
      }),
    });
  });
}

test('loads landing UI shell', async ({ page }) => {
  await mockBaseEndpoints(page);

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Ask' })).toBeVisible();
  await expect(page.locator('#queryBtn')).toBeVisible();
  await page.locator('#ingestedDetails summary').click();
  await expect(page.locator('#ingestBtn')).toBeVisible();
  await expect(page.locator('#ingestTicker')).toBeVisible();
  await expect(page.locator('#sourceViewerDetails')).toBeVisible();
  await expect(page.locator('#draftDetails')).toBeHidden();
  await expect(page.locator('#progressLogDetails')).not.toHaveAttribute('open', '');
});

test('starts ticker ingestion and shows terminal status', async ({ page }) => {
  await mockBaseEndpoints(page);

  let ingestPayload: any = null;

  await page.route('**/ingest', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    ingestPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'job-1',
        tickers: ['AMD', 'NVDA'],
        per_company: 3,
        status: 'queued',
        stage: 'queued',
        message: 'Job queued',
        created_at: '2026-02-14T00:00:00+00:00',
      }),
    });
  });

  await page.route('**/ingest/job-1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'job-1',
        tickers: ['AMD', 'NVDA'],
        per_company: 3,
        status: 'succeeded',
        stage: 'done',
        message: 'Ticker ingestion completed',
        created_at: '2026-02-14T00:00:00+00:00',
        started_at: '2026-02-14T00:00:01+00:00',
        finished_at: '2026-02-14T00:00:10+00:00',
      }),
    });
  });

  await page.goto('/');
  await page.locator('#ingestedDetails summary').click();
  await page.locator('#ingestTicker').fill('amd, nvda');
  await page.locator('#ingestPerCompany').fill('3');
  await page.locator('#ingestBtn').click();

  await expect(page.locator('#ingestJobPill')).toHaveText('succeeded');
  await expect(page.locator('#ingestJobStatus')).toContainText('Ticker ingestion completed');
  expect(ingestPayload).toEqual({ tickers: ['AMD', 'NVDA'], per_company: 3 });
});

test('citation click jumps to source chunk and markdown hr is rendered', async ({ page }) => {
  await mockBaseEndpoints(page);

  await page.route('**/source_text?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        path: SOURCE_PATH,
        text: SOURCE_TEXT,
      }),
    });
  });

  await page.route('**/query_stream', async (route) => {
    const finalAnswer =
      'Revenue growth was led by datacenter demand [doc=doc-001 chunk=chunk-2].\n\n---\n\nMargin expanded too.';

    const body = toNdjson([
      { type: 'start', request_id: 'req-12345678' },
      { type: 'status', step: 'retrieve', message: 'Retrieving chunks…' },
      { type: 'retrieved', count: CHUNKS.length, chunks: CHUNKS, step_ms: 12, elapsed_ms: 20 },
      { type: 'status', step: 'rerank', message: 'Reranking chunks…' },
      { type: 'reranked', count: CHUNKS.length, chunks: CHUNKS, step_ms: 8, elapsed_ms: 31 },
      { type: 'status', step: 'draft', message: 'Generating draft…', is_draft: true },
      { type: 'draft_delta', delta: 'Draft answer [doc=doc-001 chunk=chunk-2].' },
      { type: 'draft_done', chars: 40, step_ms: 5, elapsed_ms: 40 },
      { type: 'final_delta', delta: finalAnswer },
      {
        type: 'done',
        response: {
          draft_answer: 'Draft answer [doc=doc-001 chunk=chunk-2].',
          final_answer: finalAnswer,
          top_chunks: CHUNKS,
        },
        timing_ms: {
          retrieve_ms: 12,
          rerank_ms: 8,
          draft_ms: 5,
          final_ms: 7,
          total_ms: 32,
        },
        elapsed_ms: 45,
      },
    ]);

    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'application/x-ndjson',
      },
      body,
    });
  });

  await page.goto('/');
  await page.locator('#question').fill('What drove ACME revenue growth in Q4?');
  await page.locator('#queryBtn').click();

  const citation = page.locator('#finalAnswer a.citationLink').first();
  await expect(citation).toBeVisible();
  await expect(page.locator('#finalAnswer hr')).toHaveCount(1);

  await citation.click();

  await expect(page.locator('#sourceSelect')).toHaveValue(SOURCE_PATH);
  await expect(page.locator('#sourceContent mark.active[data-chunk-id="chunk-2"]')).toBeVisible();
});
