import Link from 'next/link'
import Image from 'next/image'
import { Mail, Phone, MapPin, Linkedin, Twitter, Facebook, Instagram } from 'lucide-react'

const footerLinks = {
  solutions: [
    { label: 'Audience Sampling', href: '/#audience-sampling' },
    { label: 'Enterprise Solutions', href: '/#enterprise-solutions' },
    { label: 'Security Measures', href: '/#security-measures' },
    { label: 'Survey Programming', href: '/#survey' },
    { label: 'Qualitative Fieldwork', href: '/#fieldwork' },
    { label: 'Market Research', href: '/#market-research' },
  ],
  company: [
    { label: 'About Us', href: '/#about' },
    { label: 'Our Team', href: '/#team' },
    { label: 'Careers', href: '/careers' },
    { label: 'Blog', href: '/blog' },
    { label: 'Contact', href: '/#contact' },
  ],
  legal: [
    { label: 'Privacy Policy', href: '/privacy-policy' },
    { label: 'Terms of Service', href: '/terms' },
    { label: 'Cookie Policy', href: '/cookies' },
    { label: 'GDPR Compliance', href: '/gdpr' },
  ],
}

const socialLinks = [
  { icon: Linkedin, href: 'https://www.linkedin.com/company/surveyfieldwork/', label: 'LinkedIn' },
  { icon: Twitter, href: 'https://twitter.com/surveyfieldwork', label: 'Twitter' },
  { icon: Facebook, href: 'https://facebook.com/surveyfieldwork', label: 'Facebook' },
  { icon: Instagram, href: 'https://instagram.com/surveyfieldwork', label: 'Instagram' },
]

export default function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="bg-secondary-900 text-white">
      {/* Main Footer */}
      <div className="container-custom py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-8">
          {/* Brand Column */}
          <div className="lg:col-span-2">
            <Link href="/" className="inline-block mb-6">
              <Image
                src="/assets/images/logo-white.png"
                alt="Survey Fieldwork"
                width={194}
                height={86}
                className="h-12 w-auto brightness-0 invert"
              />
            </Link>
            <p className="text-secondary-300 mb-6 max-w-md">
              Survey Fieldwork is a trusted partner for businesses seeking top-notch data collection and market research services. We specialize in audience sampling, survey programming, and qualitative fieldwork.
            </p>
            
            {/* Contact Info */}
            <div className="space-y-3">
              <a href="mailto:info@surveyfieldwork.com" className="flex items-center gap-3 text-secondary-300 hover:text-white transition-colors">
                <Mail size={18} className="text-primary-500" />
                info@surveyfieldwork.com
              </a>
              <a href="tel:+91-9876543210" className="flex items-center gap-3 text-secondary-300 hover:text-white transition-colors">
                <Phone size={18} className="text-primary-500" />
                +91 98765 43210
              </a>
              <div className="flex items-start gap-3 text-secondary-300">
                <MapPin size={18} className="text-primary-500 flex-shrink-0 mt-0.5" />
                <span>Cogentix Research Pvt Ltd,<br />Kolkata, West Bengal, India</span>
              </div>
            </div>
          </div>

          {/* Solutions */}
          <div>
            <h4 className="font-bold text-lg mb-4">Solutions</h4>
            <ul className="space-y-2">
              {footerLinks.solutions.map((link) => (
                <li key={link.label}>
                  <Link 
                    href={link.href}
                    className="text-secondary-300 hover:text-white transition-colors"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Company */}
          <div>
            <h4 className="font-bold text-lg mb-4">Company</h4>
            <ul className="space-y-2">
              {footerLinks.company.map((link) => (
                <li key={link.label}>
                  <Link 
                    href={link.href}
                    className="text-secondary-300 hover:text-white transition-colors"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h4 className="font-bold text-lg mb-4">Legal</h4>
            <ul className="space-y-2">
              {footerLinks.legal.map((link) => (
                <li key={link.label}>
                  <Link 
                    href={link.href}
                    className="text-secondary-300 hover:text-white transition-colors"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* Bottom Bar */}
      <div className="border-t border-secondary-800">
        <div className="container-custom py-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <p className="text-secondary-400 text-sm">
            © {currentYear} Survey Fieldwork. All rights reserved. A division of Cogentix Research Pvt Ltd.
          </p>
          
          {/* Social Links */}
          <div className="flex items-center gap-4">
            {socialLinks.map((social) => (
              <a
                key={social.label}
                href={social.href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-secondary-400 hover:text-white transition-colors"
                aria-label={social.label}
              >
                <social.icon size={20} />
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}
