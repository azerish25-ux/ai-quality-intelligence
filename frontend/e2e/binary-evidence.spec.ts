import { test } from '@playwright/test';
import { binaryEvidenceJourney } from './binary-journey';

test('executed screenshots and traces support review, exact links, revocation and worker expiry', async ({ page, request }, info) => {
  await binaryEvidenceJourney(page, request, info);
});
