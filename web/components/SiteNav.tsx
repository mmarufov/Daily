'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV = [
  { href: '/reader', label: 'Reader' },
  { href: '/evidence', label: 'Evidence' },
  { href: '/engineering', label: 'Engineering' },
] as const

export function SiteNav() {
  const pathname = usePathname()

  return (
    <nav aria-label="Sections">
      <ul className="m-0 flex list-none items-center gap-5 p-0 sm:gap-7">
        {NAV.map((item) => {
          const active = pathname === item.href
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={[
                  'label no-underline transition-colors duration-150',
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
