'use client'

import Link from 'next/link'
import { MapPin, Mail, ChevronDown } from 'lucide-react'

const impLinks = [
  { label: 'Home', href: '/' },
  { label: 'About Us', href: '/#about' },
  { label: 'Solutions', href: '/#solutions', hasDropdown: true },
  { label: 'Blogs', href: '/blog' },
  { label: 'Join Panel', href: '/#join' },
  { label: 'Book Free Consultation', href: '/#book' },
]

// Custom Logo Component for footer (with box styling)
function FooterLogo() {
  return (
    <div className="inline-flex flex-col bg-[#2a3a5a] px-4 py-3 rounded">
      <div className="flex items-center">
        <span className="text-xl font-bold text-white">Sur</span>
        <svg
          width="16"
          height="20"
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
        <span className="text-xl font-bold text-white">ey</span>
      </div>
      <span className="text-[8px] font-semibold tracking-[0.15em] text-[#0ea5e9] uppercase -mt-0.5">
        Fieldwork
      </span>
    </div>
  )
}

// Social Icon Components
function FacebookIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
      <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
    </svg>
  )
}

function LinkedInIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  )
}

function InstagramIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
    </svg>
  )
}

const socialLinks = [
  { icon: FacebookIcon, href: 'https://facebook.com/surveyfieldwork', label: 'Facebook', bgColor: 'bg-[#1877f2] hover:bg-[#166fe5]' },
  { icon: LinkedInIcon, href: 'https://www.linkedin.com/company/surveyfieldwork/', label: 'LinkedIn', bgColor: 'bg-[#0077b5] hover:bg-[#006699]' },
  { icon: InstagramIcon, href: 'https://instagram.com/surveyfieldwork', label: 'Instagram', bgColor: 'bg-gradient-to-br from-[#f58529] via-[#dd2a7b] to-[#8134af] hover:opacity-90' },
]

export default function Footer() {
  return (
    <footer className="bg-[#1e2a3a]">
      {/* Main Footer */}
      <div className="container-custom py-12">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-10">

          {/* Logo & Description Column */}
          <div>
            <div className="mb-5">
              <FooterLogo />
            </div>
            <p className="text-secondary-400 text-sm leading-relaxed">
              Delivering cutting-edge data collection methods with research-oriented accuracy in the execution of research projects.
            </p>
          </div>

          {/* Contact Info Column */}
          <div>
            <h4 className="text-white font-semibold text-lg mb-5 italic">Contact Info</h4>
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <MapPin size={16} className="text-secondary-400 flex-shrink-0 mt-1" />
                <span className="text-secondary-400 text-sm">HSR Layout, Bangalore</span>
              </div>
              <div className="flex items-center gap-3">
                <Mail size={16} className="text-secondary-400 flex-shrink-0" />
                <a
                  href="mailto:Info@surveyfieldwork.com"
                  className="text-secondary-400 text-sm hover:text-white transition-colors"
                >
                  Info@surveyfieldwork.com
                </a>
              </div>
            </div>
          </div>

          {/* Important Links Column */}
          <div>
            <h4 className="text-white font-semibold text-lg mb-5 italic">Imp Links</h4>
            <ul className="space-y-2.5">
              {impLinks.map((link) => (
                <li key={link.label}>
                  <Link
                    href={link.href}
                    className="text-secondary-400 text-sm hover:text-white transition-colors inline-flex items-center gap-1"
                  >
                    {link.label}
                    {link.hasDropdown && <ChevronDown size={12} />}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Get In Touch Column */}
          <div>
            <h4 className="text-white font-semibold text-lg mb-5 italic">Get In Touch</h4>
            <p className="text-secondary-400 text-sm leading-relaxed mb-5">
              Follow us to get latest updates. Book Free Consultation with us to get the latest market trends and insights.
            </p>

            {/* Social Links */}
            <div className="flex items-center gap-3">
              {socialLinks.map((social) => (
                <a
                  key={social.label}
                  href={social.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`w-9 h-9 rounded-full flex items-center justify-center text-white transition-all ${social.bgColor}`}
                  aria-label={social.label}
                >
                  <social.icon />
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Bar */}
      <div className="border-t border-secondary-700/50">
        <div className="container-custom py-4 flex flex-col md:flex-row items-center justify-between gap-3">
          <p className="text-secondary-500 text-sm">
            Copyright © 2026 Survey Fieldwork
          </p>
          <p className="text-secondary-500 text-sm">
            Powered by Survey Fieldwork
          </p>
        </div>
      </div>
    </footer>
  )
}

