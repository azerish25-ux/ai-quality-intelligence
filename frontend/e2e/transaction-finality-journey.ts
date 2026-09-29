import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext } from '@playwright/test';
import type { RunDetail } from '../src/api';

type Finding = { contract: string; status: string };
type Row = {
  case_id: string;
  run_id: string;
  analysis: {
    failure_id: string;
    category: string;
    supporting_evidence_ids: string[];
    claims: { predicate?: { contract?: string }; validation_status?: string }[];
    validation_results: { diagnostic_gap: string | null; diagnostic_findings: Finding[] };
  };
};

function measuredRows(): Row[] {
  const path = process.env.FAILURELENS_FINALITY_REPLAY;
  if (!path || !process.env.GITHUB_SHA) throw new Error('Exact-source finality replay is required');
  const replay = JSON.parse(readFileSync(path, 'utf8'));
  expect(replay.source_revision).toBe(process.env.GITHUB_SHA);
  expect(replay.source_worktree_dirty).toBe(false);
  expect(replay.database_dialect).toBe('postgresql');
  expect(replay.cases).toHaveLength(8);
  return replay.cases;
}

async function projectForRun(request: APIRequestContext, id: string): Promise<string> {
  const response = await request.get(`http://127.0.0.1:8000/api/v1/runs/${id}`);
  expect(response.ok()).toBeTruthy();
  const detail: RunDetail = await response.json();
  expect(detail.run.id).toBe(id);
  expect(detail.run.project_id).toMatch(/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i);
  return detail.run.project_id;
}

for (const category of ['product_defect', 'insufficient_evidence']) {
  test(`inspect finality ${category} without hiding its evidence boundary`, async ({ page, request }, info) => {
    const rows = measuredRows().filter(row => row.analysis.category === category);
    expect(rows).toHaveLength(4);
    for (const row of rows) {
      expect(row.case_id).toMatch(/^c-[0-9a-f]{20}$/);
      const project = await projectForRun(request, row.run_id);
      await page.goto(`/?project=${project}&run=${row.run_id}&failure=${row.analysis.failure_id}#workspace`);
      const diagnostic = page.getByRole('region', { name: 'Diagnostic evidence', exact: true });
      await expect(diagnostic).toBeVisible();
      const supported = category === 'product_defect';
      await expect(diagnostic.getByText(`transaction finality · ${supported ? 'violated' : 'incomplete'}`, { exact: true })).toBeVisible();
      await expect(diagnostic.getByText('A conforming narrow check does not establish that the failure or product is harmless.', { exact: true })).toBeVisible();
      if (supported) {
        expect(row.analysis.validation_results.diagnostic_gap).toBeNull();
        expect(row.analysis.claims).toHaveLength(1);
        expect(row.analysis.claims[0].predicate?.contract).toBe('transaction_finality');
        expect(row.analysis.claims[0].validation_status).toBe('verified');
        expect(row.analysis.supporting_evidence_ids.length).toBeGreaterThan(0);
      } else {
        expect(row.analysis.claims).toHaveLength(0);
        await expect(diagnostic.getByRole('status')).toHaveText('Required observations are missing or invalid.');
      }
      for (const id of row.analysis.supporting_evidence_ids) {
        expect((await request.get(`http://127.0.0.1:8000/api/v1/evidence/${id}`)).ok()).toBeTruthy();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
      await diagnostic.screenshot({ path: info.outputPath(`${row.case_id}.png`) });
    }
  });
}
