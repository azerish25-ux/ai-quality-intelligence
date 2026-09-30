import { test } from '@playwright/test';
import { providerJourney } from './provider-journey';

test.use({ trace: 'off' });
test('provider consent and persisted state remain accessible at 390px', async ({ page, request }, info) => {
  await providerJourney(page, request, info);
});
