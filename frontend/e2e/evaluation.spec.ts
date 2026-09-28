import { test } from '@playwright/test';
import { evaluationJourney } from './evaluation-journey';
test('shows actual executed provenance and failed quality targets without invented five-class scores', async ({ page, request }, info) => {
  await evaluationJourney(page, request, info);
});
