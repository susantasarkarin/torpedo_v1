'use client'

import Link from 'next/link'
import Image from 'next/image'
import { useState, useEffect } from 'react'
import { Menu, X, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

// Navigation items matching WordPress structure
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

export default function Header() {
  const [isOpen, setIsOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [openDropdown, setOpenDropdown] = useState<string | null>(null)

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 50)
    }
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  return (
    <header 
      className={cn(
        'fixed top-0 left-0 right-0 z-50 transition-all duration-300',
        scrolled ? 'bg-white shadow-soft py-2' : 'bg-transparent py-4'
      )}
    >
      <div className="container-custom">
        <div className="flex items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center">
            <Image
              src="/assets/images/logo.png"
              alt="Survey Fieldwork"
              width={194}
              height={86}
              className="h-12 w-auto"
              priority
            />
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden lg:flex items-center gap-6">
            {navItems.map((item) => (
              <div key={item.label} className="relative group">
                {item.children ? (
                  <>
                    <button 
                      className={cn(
                        'flex items-center gap-1 font-semibold text-[15px] transition-colors',
                        scrolled ? 'text-secondary-900 hover:text-primary-600' : 'text-secondary-900 hover:text-primary-600'
                      )}
                      onClick={() => setOpenDropdown(openDropdown === item.label ? null : item.label)}
                    >
                      {item.label}
                      <ChevronDown size={16} className="transition-transform group-hover:rotate-180" />
                    </button>
                    
                    {/* Dropdown Menu */}
                    <div className="absolute top-full left-0 pt-2 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200">
                      <div className="bg-white rounded-xl shadow-medium border border-secondary-100 py-2 min-w-[220px]">
                        {item.children.map((child) => (
                          <div key={child.label}>
                            {child.children ? (
                              <div className="group/sub relative">
                                <span className="block px-4 py-2 text-sm font-medium text-secondary-700 hover:bg-primary-50 hover:text-primary-600 cursor-pointer">
                                  {child.label}
                                </span>
                                <div className="absolute left-full top-0 pl-1 opacity-0 invisible group-hover/sub:opacity-100 group-hover/sub:visible transition-all">
                                  <div className="bg-white rounded-xl shadow-medium border border-secondary-100 py-2 min-w-[200px]">
                                    {child.children.map((subChild) => (
                                      <Link
                                        key={subChild.label}
                                        href={subChild.href}
                                        className="block px-4 py-2 text-sm text-secondary-600 hover:bg-primary-50 hover:text-primary-600"
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
                                className="block px-4 py-2 text-sm text-secondary-600 hover:bg-primary-50 hover:text-primary-600"
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
                    className={cn(
                      'font-semibold text-[15px] transition-colors',
                      scrolled ? 'text-secondary-900 hover:text-primary-600' : 'text-secondary-900 hover:text-primary-600'
                    )}
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
            className="hidden lg:inline-flex btn-primary text-sm"
          >
            Panel Login
          </Link>

          {/* Mobile Menu Toggle */}
          <button 
            className="lg:hidden p-2 text-secondary-900"
            onClick={() => setIsOpen(!isOpen)}
            aria-label="Toggle menu"
          >
            {isOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>

        {/* Mobile Navigation */}
        {isOpen && (
          <nav className="lg:hidden mt-4 pb-4 border-t border-secondary-200 pt-4">
            <div className="flex flex-col gap-2">
              {navItems.map((item) => (
                <div key={item.label}>
                  {item.children ? (
                    <div>
                      <button 
                        className="flex items-center justify-between w-full py-2 text-secondary-900 font-medium"
                        onClick={() => setOpenDropdown(openDropdown === item.label ? null : item.label)}
                      >
                        {item.label}
                        <ChevronDown size={16} className={cn(
                          'transition-transform',
                          openDropdown === item.label && 'rotate-180'
                        )} />
                      </button>
                      {openDropdown === item.label && (
                        <div className="pl-4 space-y-2">
                          {item.children.map((child) => (
                            <Link
                              key={child.label}
                              href={child.href || '#'}
                              className="block py-1 text-sm text-secondary-600"
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
                      className="block py-2 text-secondary-900 font-medium"
                      onClick={() => setIsOpen(false)}
                    >
                      {item.label}
                    </Link>
                  )}
                </div>
              ))}
              <Link
                href="https://panel.surveyfieldwork.com"
                className="btn-primary text-center mt-4"
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
