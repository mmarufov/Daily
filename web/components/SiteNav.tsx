'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV = [
  { href: '/lab', label: 'Lab' },
  { href: '/engineering', label: 'Case study' },
] as const

export function SiteNav() {
  const pathname = usePathname()
  return (
    <nav aria-label="Sections">
      <ul className="site-nav">
        {NAV.map((item) => (
          <li key={item.href}>
            <Link href={item.href} aria-current={pathname === item.href || pathname.startsWith(`${item.href}/`) ? 'page' : undefined}>{item.label}</Link>
          </li>
        ))}
        <li><a href="https://github.com/mmarufov/Daily" rel="noreferrer">GitHub</a></li>
      </ul>
    </nav>
  )
}
