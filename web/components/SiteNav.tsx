'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV = [
  { href: '/reader', label: 'Reader' },
  { href: '/lab', label: 'Lab' },
  { href: '/evidence', label: 'Evidence' },
  { href: '/engineering', label: 'Findings' },
] as const

export function SiteNav() {
  const pathname = usePathname()
  return (
    <nav aria-label="Sections">
      <ul className="site-nav">
        {NAV.map((item) => (
          <li key={item.href}>
            <Link href={item.href} prefetch={item.href === '/reader' ? false : null} aria-current={pathname === item.href || pathname.startsWith(`${item.href}/`) ? 'page' : undefined}>{item.label}</Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
