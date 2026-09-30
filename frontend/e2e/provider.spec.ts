import { test } from '@playwright/test';
import { providerJourney } from './provider-journey';

// Login responses contain synthetic fixture session credentials. Preserve only
// screenshots of the safe UI, never browser request traces or fixture metadata.
test.use({ trace: 'off' });
test('optional provider uses an authenticated durable API with explicit evidence consent and honest fallbacks', async ({ page, request }, info) => {
  await providerJourney(page, request, info);
});
