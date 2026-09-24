'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV = [
  { href: '/reader', label: 'Reader' },
  { href: '/evidence', label: 'Evidence' },
  { href: '/lab', label: 'Lab' },
  { href: '/engineering', label: 'Engineering' },
] as const

export function SiteNav() {
  const pathname = usePathname()

  return (
    // Scrolls rather than wraps below 360px. Four labels at this size cannot
    // fit a 320px screen, and wrapping them pushes the wordmark onto its own
    // line and doubles the header height on the smallest device -- where
    // vertical space is scarcest. A scroll keeps the header one row tall and
    // the overflow stays inside the nav instead of tipping the whole page
    // sideways, which is what it was doing.
    <nav aria-label="Sections" className="-mx-2 min-w-0 overflow-x-auto px-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <ul className="m-0 flex list-none items-center gap-3 whitespace-nowrap p-0 sm:gap-5">
        {NAV.map((item) => {
          const active = pathname === item.href
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={[
                  'label -my-1 inline-block py-2 no-underline transition-colors duration-150',
                  active
                    ? 'text-ink underline decoration-signal decoration-1 underline-offset-[6px]'
                    : 'text-ink-60 hover:text-ink',
                ].join(' ')}
              >
                {item.label}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
