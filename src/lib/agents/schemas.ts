/**
 * The schema each LLM-backed agent extracts against, keyed by agent name.
 *
 * This registry exists for one consumer: `scripts/record-fixture.ts`, which is
 * how a Claude session acting as the agent tier writes its extractions to disk.
 * Validating against the same schema the production agent uses means a fixture
 * that would not satisfy the agent cannot be recorded in the first place.
 */

import { z } from 'zod';
import { ContextRiskSchema } from './context-scanner';
import { LocatorFallbackSchema } from './source-locator';
import { ResolutionSpecSchema } from './types';

export const AGENT_SCHEMAS: Record<string, z.ZodType> = {
  'resolution-parser': ResolutionSpecSchema,
  'source-locator': LocatorFallbackSchema,
  'context-scanner': ContextRiskSchema,
};
