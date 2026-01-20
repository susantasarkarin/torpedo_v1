'use client'

import { motion } from 'framer-motion'
import { useState } from 'react'
import { Send, Mail, Phone, MapPin, Clock, ArrowRight, CheckCircle } from 'lucide-react'
import { contactContent as defaultContent } from '@/lib/content'

const iconMap: Record<string, React.ElementType> = {
  Mail,
  Phone,
  MapPin,
  Clock,
}

interface ContactProps {
  content?: typeof defaultContent
}

export default function Contact({ content = defaultContent }: ContactProps) {
  const { badge, title, titleHighlight, description, contactInfo: contactItems, whyChooseUs, form } = content
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    company: '',
    phone: '',
    service: '',
    message: '',
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSubmitted, setIsSubmitted] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSubmitting(true)
    
    // Simulate form submission
    await new Promise(resolve => setTimeout(resolve, 1500))
    
    setIsSubmitting(false)
    setIsSubmitted(true)
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value })
  }

  // Process contact info with icon components
  const contactInfoWithIcons = contactItems.map(item => ({
    ...item,
    IconComponent: iconMap[item.icon] || Mail
  }))

  return (
    <section id="book" className="section-padding bg-secondary-50">
      <div className="container-custom">
        <div className="grid lg:grid-cols-2 gap-12">
          {/* Left - Contact Info */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
          >
            <span className="inline-block px-4 py-2 bg-primary-100 text-primary-700 text-sm font-semibold rounded-full mb-4">
              {badge}
            </span>
            <h2 className="text-3xl md:text-4xl font-bold text-secondary-900 mb-6">
              {title}{' '}
              <span className="gradient-text">{titleHighlight}</span>
            </h2>
            <p className="text-lg text-secondary-600 mb-8">
              {description}
            </p>

            {/* Contact Cards */}
            <div className="grid sm:grid-cols-2 gap-4 mb-8">
              {contactInfoWithIcons.map((info) => (
                <a
                  key={info.title}
                  href={info.href}
                  className="bg-white rounded-xl p-4 shadow-soft hover:shadow-medium transition-shadow group"
                >
                  <div className="w-10 h-10 bg-primary-100 rounded-lg flex items-center justify-center mb-3 group-hover:bg-primary-500 transition-colors">
                    <info.IconComponent className="text-primary-600 group-hover:text-white transition-colors" size={20} />
                  </div>
                  <div className="font-semibold text-secondary-900">{info.title}</div>
                  <div className="text-sm text-secondary-500">{info.details}</div>
                </a>
              ))}
            </div>

            {/* Map or Additional Info */}
            <div className="bg-gradient-to-br from-primary-500 to-accent-500 rounded-2xl p-6 text-white">
              <h3 className="text-xl font-bold mb-3">{whyChooseUs.title}</h3>
              <ul className="space-y-2">
                {whyChooseUs.items.map((item) => (
                  <li key={item} className="flex items-center gap-2">
                    <CheckCircle size={18} />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </motion.div>

          {/* Right - Contact Form */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
          >
            <div className="bg-white rounded-2xl shadow-medium p-8">
              {isSubmitted ? (
                <div className="text-center py-12">
                  <div className="w-16 h-16 bg-accent-100 rounded-full flex items-center justify-center mx-auto mb-4">
                    <CheckCircle className="text-accent-500" size={32} />
                  </div>
                  <h3 className="text-2xl font-bold text-secondary-900 mb-2">Thank You!</h3>
                  <p className="text-secondary-600 mb-6">
                    We've received your message and will get back to you within 24 hours.
                  </p>
                  <button
                    onClick={() => {
                      setIsSubmitted(false)
                      setFormData({
                        name: '',
                        email: '',
                        company: '',
                        phone: '',
                        service: '',
                        message: '',
                      })
                    }}
                    className="btn-outline"
                  >
                    Send Another Message
                  </button>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-5">
                  <h3 className="text-xl font-bold text-secondary-900 mb-4">
                    Get in Touch
                  </h3>

                  <div className="grid sm:grid-cols-2 gap-4">
                    <div>
                      <label htmlFor="name" className="block text-sm font-medium text-secondary-700 mb-1">
                        Full Name *
                      </label>
                      <input
                        type="text"
                        id="name"
                        name="name"
                        value={formData.name}
                        onChange={handleChange}
                        required
                        className="w-full px-4 py-3 rounded-lg border border-secondary-300 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 outline-none transition-all"
                        placeholder="John Doe"
                      />
                    </div>
                    <div>
                      <label htmlFor="email" className="block text-sm font-medium text-secondary-700 mb-1">
                        Email Address *
                      </label>
                      <input
                        type="email"
                        id="email"
                        name="email"
                        value={formData.email}
                        onChange={handleChange}
                        required
                        className="w-full px-4 py-3 rounded-lg border border-secondary-300 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 outline-none transition-all"
                        placeholder="john@company.com"
                      />
                    </div>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-4">
                    <div>
                      <label htmlFor="company" className="block text-sm font-medium text-secondary-700 mb-1">
                        Company
                      </label>
                      <input
                        type="text"
                        id="company"
                        name="company"
                        value={formData.company}
                        onChange={handleChange}
                        className="w-full px-4 py-3 rounded-lg border border-secondary-300 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 outline-none transition-all"
                        placeholder="Company Name"
                      />
                    </div>
                    <div>
                      <label htmlFor="phone" className="block text-sm font-medium text-secondary-700 mb-1">
                        Phone Number
                      </label>
                      <input
                        type="tel"
                        id="phone"
                        name="phone"
                        value={formData.phone}
                        onChange={handleChange}
                        className="w-full px-4 py-3 rounded-lg border border-secondary-300 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 outline-none transition-all"
                        placeholder="+91 98765 43210"
                      />
                    </div>
                  </div>

                  <div>
                    <label htmlFor="service" className="block text-sm font-medium text-secondary-700 mb-1">
                      Service Interested In
                    </label>
                    <select
                      id="service"
                      name="service"
                      value={formData.service}
                      onChange={handleChange}
                      className="w-full px-4 py-3 rounded-lg border border-secondary-300 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 outline-none transition-all"
                    >
                      <option value="">Select a service</option>
                      <option value="audience-sampling">Audience Sampling</option>
                      <option value="enterprise">Enterprise Solutions</option>
                      <option value="survey">Survey Programming & Hosting</option>
                      <option value="qualitative">Qualitative Fieldwork</option>
                      <option value="market-research">Market Research & Insights</option>
                      <option value="other">Other</option>
                    </select>
                  </div>

                  <div>
                    <label htmlFor="message" className="block text-sm font-medium text-secondary-700 mb-1">
                      Your Message *
                    </label>
                    <textarea
                      id="message"
                      name="message"
                      value={formData.message}
                      onChange={handleChange}
                      required
                      rows={4}
                      className="w-full px-4 py-3 rounded-lg border border-secondary-300 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 outline-none transition-all resize-none"
                      placeholder="Tell us about your project..."
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="btn-primary w-full justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isSubmitting ? (
                      <>
                        <span className="animate-spin mr-2">⏳</span>
                        Sending...
                      </>
                    ) : (
                      <>
                        Send Message
                        <Send size={18} className="ml-2" />
                      </>
                    )}
                  </button>

                  <p className="text-xs text-secondary-500 text-center">
                    By submitting this form, you agree to our{' '}
                    <a href="/privacy-policy" className="text-primary-600 hover:underline">Privacy Policy</a>
                  </p>
                </form>
              )}
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  )
}
