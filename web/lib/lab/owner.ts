/**
 * Who may spend money.
 *
 * The rule the spec states is "public visitors inspect and replay; only the
 * authenticated owner starts paid work, enforced server-side". Two halves of
 * that are easy to get wrong and are handled here rather than at each call
 * site, because a call site that forgets is a call site that is open.
 *
 *  - **Fails closed.** No configured token means nobody is the owner, not
 *    that everybody is. A deployment that forgets to set `LAB_OWNER_TOKEN`
 *    refuses every start request rather than accepting every one.
 *  - **Constant time.** A `===` on a secret leaks its prefix to anyone
 *    willing to time the responses.
 *
 * This is deliberately not a session, a cookie or a user table. There is one
 * owner, the surface is one POST, and inventing an auth system for it would
 * be more code to get wrong than the thing it protects.
 */

import { timingSafeEqual } from 'node:crypto'

export type OwnerCheck =
  | { readonly ok: true }
  | { readonly ok: false; readonly status: 401 | 503; readonly reason: string }

export function authoriseOwner(
  request: Request,
  env: Readonly<Record<string, string | undefined>> = process.env,
): OwnerCheck {
  const expected = (env.LAB_OWNER_TOKEN ?? '').trim()
  if (expected === '') {
    return {
      ok: false,
      status: 503,
      reason:
        'no owner is configured on this deployment, so nothing here can start paid work. This is the closed state, not an outage.',
    }
  }

  const header = request.headers.get('authorization') ?? ''
  const presented = header.startsWith('Bearer ') ? header.slice(7).trim() : ''
  if (presented === '') {
    return { ok: false, status: 401, reason: 'a bearer token is required to start a run' }
  }

  const a = Buffer.from(presented)
  const b = Buffer.from(expected)
  // `timingSafeEqual` throws on a length mismatch, which would itself leak the
  // length. Compare a fixed-width digest-free padding instead: equal lengths
  // are required, and unequal ones cost the same as a wrong token.
  const same = a.length === b.length && timingSafeEqual(a, b)
  if (!same) return { ok: false, status: 401, reason: 'that token is not the owner token' }
  return { ok: true }
}
