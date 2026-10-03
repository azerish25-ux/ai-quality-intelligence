import { test } from '@playwright/test';
import { workbenchJourney } from './workbench-journey';
test('investigation-first workbench preserves scope, selection and accessible navigation', async ({ page }, info) => {
  await workbenchJourney(page, info);
});
