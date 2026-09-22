/**
 * Where a *running* function finds the Lab's evidence.
 *
 * Not `../backend/`. Next's file tracing refuses a glob that navigates out of
 * the project root, and moving the tracing root to the repository breaks
 * Turbopack's module resolution — so a deployed function cannot read
 * `backend/` at all, however well that path works on a laptop. It answered
 * `ENOENT` in production while every local check passed.
 *
 * `scripts/stage-lab-evidence.ts` copies the needed files here before dev and
 * before build. The directory is gitignored: a second committed copy of the
 * case suite would be a second thing that can disagree with the first.
 *
 * The *export* still reads `backend/` directly, and should — it runs on a
 * developer's machine, and its whole job is to be a function of committed
 * bytes rather than of a build artifact.
 */

import { join } from 'node:path'

export const EVIDENCE_ROOT = join(process.cwd(), 'lab-evidence')

export const LAB_DIR = join(EVIDENCE_ROOT, 'backend', 'lab')
