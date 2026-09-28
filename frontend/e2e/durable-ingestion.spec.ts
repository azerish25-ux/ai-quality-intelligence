import { expect, test } from '@playwright/test';

test('uploads a real JUnit report and opens the automatically analyzed run', async ({ page }, testInfo) => {
  const projectSuffix = `${testInfo.project.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${testInfo.retry}`;
  const externalRunId = `browser-e2e-${projectSuffix}`;
  const testClassName = `Transfer-${projectSuffix}`;
  const testIdentity = `${testClassName}::duplicate`;
  await page.goto('/');
  await expect(page.getByText('Synthetic demo identity.')).toBeVisible();
  await page.getByRole('button', { name: 'Load synthetic demo' }).click();
  await expect(page.getByRole('heading', { name: 'Upload an actual test report' })).toBeVisible();

  await page.getByLabel('External run ID').fill(externalRunId);
  await page.getByLabel('Expected required inputs').fill('1');
  await page.getByLabel('Report file').setInputFiles({
    name: 'browser-junit.xml',
    mimeType: 'application/xml',
    buffer: Buffer.from(
      `<testsuite name="payments"><testcase classname="${testClassName}" name="duplicate" time="0.12"><failure type="LedgerInvariantError" message="duplicate committed transfer">ledger unbalanced after double charge</failure></testcase></testsuite>`
    )
  });
  await page.getByRole('button', { name: 'Queue ingestion' }).click();

  const ingestion = page.locator('.ingestion-row', { hasText: externalRunId });
  await expect(ingestion).toBeVisible();
  await expect(ingestion.getByText('Succeeded')).toBeVisible();
  await ingestion.getByRole('button', { name: 'Open run' }).click();
  await expect(page.getByRole('heading', { name: 'Run inputs and completeness' })).toBeVisible();
  await expect(page.locator('.input-row', { hasText: 'browser-junit.xml' })).toContainText('accepted');
  await expect(page.locator('.input-summary')).toContainText('1');

  await expect(page.getByRole('heading', { name: 'Failure clusters' })).toBeVisible();
  const cluster = page.locator('.cluster-row', { hasText: testIdentity });
  await expect(cluster).toBeVisible();
  await cluster.click();
  await expect(page.locator('.cluster-detail')).toContainText('explainable-complete-link-v1');
  await expect(page.locator('.cluster-detail').getByText('Candidate-generation reasons', { exact: true }).first()).toBeVisible();
  await expect(page.locator('.cluster-workspace')).toContainText('Similarity groups investigation signals');

  const failure = page.locator('.failure-row', { hasText: testIdentity });
  await expect(failure).toBeVisible();
  await failure.click();
  await expect(
    page.locator('.analysis-summary').getByText('Probable product defect', { exact: true })
  ).toBeVisible();
  await expect(page.locator('.analysis-summary').getByText(/validated current-run observations/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Historical test intelligence' })).toBeVisible();
  await expect(page.locator('.history-context')).toContainText('Current run is excluded');
  await expect(page.locator('.history-panel')).toContainText('No prior matching observations');
  await expect(page.locator('.history-warning')).toContainText('no prior matching observations');
  await expect(page.getByRole('heading', { name: 'Infrastructure context' })).toBeVisible();
  await expect(page.getByRole('note')).toContainText('associations, not proof of cause');
  await page.getByRole('button', { name: 'Persist immutable correlation snapshot' }).click();
  await expect(page.getByRole('button', { name: 'Snapshot persisted' })).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Performance regression analysis' })).toBeVisible();
  await expect(page.locator('.performance-observation-row')).toContainText('test.duration');
  await page.getByRole('button', { name: 'Compare compatible baselines' }).click();
  await expect(page.locator('.performance-comparison-card')).toContainText(/incompatible baseline/i);
  await expect(page.locator('.performance-comparison-card')).toContainText(/current run untrusted/i);
  await expect(page.locator('.performance-comparison-card').getByRole('link', { name: 'Current metric evidence' })).toBeVisible();

  const analysisReview = page.getByRole('region', { name: 'Human analysis review' });
  await analysisReview.getByLabel('Engineering reason').fill(
    'The approved evidence supports the deterministic category for this controlled run.'
  );
  await analysisReview.getByRole('button', { name: 'Record append-only decision' }).click();
  await expect(analysisReview).toContainText(/Synthetic demo administrator · version \d+/);

  await page.locator('#settings').scrollIntoViewIfNeeded();
  const credentialName = `browser-ingestion-${projectSuffix}`;
  await page.getByLabel('Credential name').fill(credentialName);
  await page.getByRole('button', { name: 'Create token' }).click();
  await expect(page.getByText('Copy this secret now. It will not be shown again.')).toBeVisible();
  const credentialRow = page.locator('.token-list li', { hasText: credentialName });
  await credentialRow.getByRole('button', { name: 'Revoke' }).click();
  await expect(credentialRow.getByText('Revoked', { exact: true })).toBeVisible();
});

test('builds an explainable focused recommendation and records an attributed override', async ({ page }, testInfo) => {
  const projectSuffix = `${testInfo.project.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${testInfo.retry}`;
  const seedResponse = await page.request.post('http://127.0.0.1:5173/api/v1/demo/seed');
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json() as { project_id: string };

  const baseSha = '1'.repeat(40);
  const headSha = '2'.repeat(40);
  const query = new URLSearchParams({
    external_id: `impact-browser-e2e-${projectSuffix}`,
    filename: 'changes.json',
    repository: 'owner/repo',
    base_sha: baseSha,
    commit_sha: headSha,
    comparison_trust: 'trusted_workflow',
    expected_inputs: '1'
  });
  const uploadResponse = await page.request.post(
    `http://127.0.0.1:5173/api/v1/projects/${seed.project_id}/ingestions?${query.toString()}`,
    {
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({
        base_sha: baseSha,
        head_sha: headSha,
        complete: true,
        // This artifact claim is preserved only for audit. Effective trust comes
        // from the authenticated comparison_trust transport metadata above.
        trust: 'self_reported',
        files: [{ status: 'modified', path: 'src/checkout.py' }]
      })
    }
  );
  expect(uploadResponse.status()).toBe(202);
  const queued = await uploadResponse.json() as { id: string };

  let impactRunId = '';
  await expect.poll(async () => {
    const response = await page.request.get(
      `http://127.0.0.1:5173/api/v1/ingestions/${queued.id}`
    );
    const body = await response.json() as { state: string; run_id: string | null };
    impactRunId = body.run_id ?? '';
    return body.state;
  }).toBe('succeeded');
  expect(impactRunId).not.toBe('');

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Focused test recommendation' })).toBeVisible();
  await page.getByLabel('Impact run').selectOption(impactRunId);

  const editor = page.locator('details.impact-mapping-editor');
  await editor.getByText('Register an immutable mapping snapshot').click();
  const manifest = JSON.parse(await editor.getByLabel('Impact mapping manifest').inputValue()) as Record<string, unknown>;
  manifest.version = `mapping-browser-e2e-${projectSuffix}-v1`;
  await editor.getByLabel('Impact mapping manifest').fill(JSON.stringify(manifest, null, 2));
  await editor.getByRole('button', { name: 'Register mapping snapshot' }).click();

  await expect(page.getByRole('combobox', { name: /Impact mapping/i })).toContainText(`mapping-browser-e2e-${projectSuffix}-v1`);
  await page.getByRole('button', { name: 'Generate recommendation' }).click();
  await expect(page.locator('.impact-summary')).toContainText('FOCUSED SUBSET');
  await expect(page.getByRole('region', { name: 'Selected impact tests' })).toContainText('submits payment');
  await expect(page.getByRole('region', { name: 'Excluded impact tests' })).toContainText('updates avatar');

  await page.getByLabel('Impact override reason').fill(
    'Reviewed release-risk coupling not represented in the current coverage snapshot.'
  );
  await page.getByRole('region', { name: 'Excluded impact tests' }).getByRole('button', { name: 'Include' }).click();

  await expect(page.getByRole('region', { name: 'Impact override audit' })).toContainText('include profile');
  await expect(page.getByRole('region', { name: 'Impact override audit' })).toContainText('Synthetic demo administrator');
  await expect(page.locator('.impact-summary')).toContainText('1 audited override');
});
