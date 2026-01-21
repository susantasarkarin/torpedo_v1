'use client'

import Link from 'next/link'
import { useState, useEffect } from 'react'
import { Menu, X, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

// Navigation items matching the reference design
const navItems = [
  { label: 'Home', href: '/' },
  { label: 'About Us', href: '/#about' },
  {
    label: 'Solutions',
    href: '#',
    children: [
      {
        label: 'Online Sampling',
        children: [
          { label: 'Audience Sampling', href: '/#audience-sampling' },
          { label: 'Enterprise Solutions', href: '/#enterprise-solutions' },
          { label: 'Security Measures', href: '/#security-measures' },
        ]
      },
      { label: 'Survey Programming & Hosting', href: '/#survey' },
      { label: 'Qualitative Fieldwork', href: '/#fieldwork' },
      { label: 'Market Research & Insights', href: '/#market-research' },
    ]
  },
  { label: 'Blogs', href: '/blog' },
  { label: 'Join Panel', href: '/#join' },
  { label: 'Book Free Consultation', href: '/#book' },
]

// Custom Logo Component matching the reference
function Logo() {
  return (
    <div className="flex flex-col">
      <div className="flex items-center">
        <span className="text-2xl font-bold text-[#1a2b4a]">Sur</span>
        <svg
          width="20"
          height="24"
          viewBox="0 0 20 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="mx-0.5"
        >
          <path
            d="M2 12L8 18L18 6"
            stroke="#0ea5e9"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="text-2xl font-bold text-[#1a2b4a]">ey</span>
      </div>
      <span className="text-[10px] font-semibold tracking-[0.2em] text-[#0ea5e9] uppercase -mt-1">
        Fieldwork
      </span>
    </div>
  )
}

export default function Header() {
  const [isOpen, setIsOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [openDropdown, setOpenDropdown] = useState<string | null>(null)

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 10)
    }
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  return (
    <header
      className={cn(
        'fixed top-0 left-0 right-0 z-50 transition-all duration-300 bg-white',
        scrolled ? 'shadow-md py-3' : 'shadow-sm py-4'
      )}
    >
      <div className="container-custom">
        <div className="flex items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center hover:opacity-90 transition-opacity">
            <Logo />
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden lg:flex items-center gap-8">
            {navItems.map((item) => (
              <div key={item.label} className="relative group">
                {item.children ? (
                  <>
                    <button
                      className="flex items-center gap-1 text-[15px] font-medium text-secondary-700 hover:text-primary-500 transition-colors py-2"
                      onClick={() => setOpenDropdown(openDropdown === item.label ? null : item.label)}
                    >
                      {item.label}
                      <ChevronDown size={14} className="transition-transform duration-200 group-hover:rotate-180" />
                    </button>

                    {/* Dropdown Menu */}
                    <div className="absolute top-full left-0 pt-2 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 transform translate-y-1 group-hover:translate-y-0">
                      <div className="bg-white rounded-lg shadow-lg border border-secondary-100 py-2 min-w-[220px]">
                        {item.children.map((child) => (
                          <div key={child.label}>
                            {child.children ? (
                              <div className="group/sub relative">
                                <span className="flex items-center justify-between px-4 py-2.5 text-sm font-medium text-secondary-700 hover:bg-primary-50 hover:text-primary-600 cursor-pointer">
                                  {child.label}
                                  <ChevronDown size={12} className="-rotate-90" />
                                </span>
                                <div className="absolute left-full top-0 pl-1 opacity-0 invisible group-hover/sub:opacity-100 group-hover/sub:visible transition-all">
                                  <div className="bg-white rounded-lg shadow-lg border border-secondary-100 py-2 min-w-[200px]">
                                    {child.children.map((subChild) => (
                                      <Link
                                        key={subChild.label}
                                        href={subChild.href}
                                        className="block px-4 py-2.5 text-sm text-secondary-600 hover:bg-primary-50 hover:text-primary-600"
                                      >
                                        {subChild.label}
                                      </Link>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            ) : (
                              <Link
                                href={child.href || '#'}
                                className="block px-4 py-2.5 text-sm text-secondary-600 hover:bg-primary-50 hover:text-primary-600"
                              >
                                {child.label}
                              </Link>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                ) : (
                  <Link
                    href={item.href}
                    className="text-[15px] font-medium text-secondary-700 hover:text-primary-500 transition-colors py-2"
                  >
                    {item.label}
                  </Link>
                )}
              </div>
            ))}
          </nav>

          {/* Panel Login Button */}
          <Link
            href="https://panel.surveyfieldwork.com"
            className="hidden lg:inline-flex items-center justify-center px-5 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-md transition-all duration-200 hover:shadow-md"
          >
            Panel Login
          </Link>

          {/* Mobile Menu Toggle */}
          <button
            className="lg:hidden p-2 text-secondary-700 hover:text-secondary-900 transition-colors"
            onClick={() => setIsOpen(!isOpen)}
            aria-label="Toggle menu"
          >
            {isOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>

        {/* Mobile Navigation */}
        {isOpen && (
          <nav className="lg:hidden mt-4 pb-4 border-t border-secondary-200 pt-4 animate-fade-in">
            <div className="flex flex-col gap-1">
              {navItems.map((item) => (
                <div key={item.label}>
                  {item.children ? (
                    <div>
                      <button
                        className="flex items-center justify-between w-full py-3 text-secondary-700 font-medium hover:text-primary-500 transition-colors"
                        onClick={() => setOpenDropdown(openDropdown === item.label ? null : item.label)}
                      >
                        {item.label}
                        <ChevronDown size={16} className={cn(
                          'transition-transform duration-200',
                          openDropdown === item.label && 'rotate-180'
                        )} />
                      </button>
                      {openDropdown === item.label && (
                        <div className="pl-4 space-y-1 pb-2 animate-fade-in">
                          {item.children.map((child) => (
                            <Link
                              key={child.label}
                              href={child.href || '#'}
                              className="block py-2 text-sm text-secondary-600 hover:text-primary-500 transition-colors"
                              onClick={() => setIsOpen(false)}
                            >
                              {child.label}
                            </Link>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <Link
                      href={item.href}
                      className="block py-3 text-secondary-700 font-medium hover:text-primary-500 transition-colors"
                      onClick={() => setIsOpen(false)}
                    >
                      {item.label}
                    </Link>
                  )}
                </div>
              ))}
              <Link
                href="https://panel.surveyfieldwork.com"
                className="mt-4 flex items-center justify-center px-5 py-3 bg-primary-500 hover:bg-primary-600 text-white font-medium rounded-md transition-all"
                onClick={() => setIsOpen(false)}
              >
                Panel Login
              </Link>
            </div>
          </nav>
        )}
      </div>
    </header>
  )
}

