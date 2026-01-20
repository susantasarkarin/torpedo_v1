'use client'

import { motion } from 'framer-motion'
import { 
  Users, 
  Building2, 
  Shield, 
  MonitorPlay, 
  MessageCircle, 
  TrendingUp,
  ArrowRight,
  LucideIcon
} from 'lucide-react'
import Link from 'next/link'
import { servicesContent as defaultContent } from '@/lib/content'

// Icon mapping for dynamic icon rendering
const iconMap: Record<string, LucideIcon> = {
  Users,
  Building2,
  Shield,
  MonitorPlay,
  MessageCircle,
  TrendingUp,
}

interface ServicesProps {
  content?: typeof defaultContent
}

const colorVariants = {
  primary: {
    bg: 'bg-primary-50',
    icon: 'bg-primary-100 text-primary-600',
    badge: 'bg-primary-100 text-primary-700',
    hover: 'group-hover:bg-primary-100',
  },
  accent: {
    bg: 'bg-accent-50',
    icon: 'bg-accent-100 text-accent-600',
    badge: 'bg-accent-100 text-accent-700',
    hover: 'group-hover:bg-accent-100',
  },
}

export default function Services({ content = defaultContent }: ServicesProps) {
  const { sectionTitle, headline, description, services } = content

  return (
    <section id="solutions" className="section-padding bg-white">
      <div className="container-custom">
        {/* Section Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-16"
        >
          <span className="inline-block px-4 py-2 bg-primary-100 text-primary-700 text-sm font-semibold rounded-full mb-4">
            {sectionTitle}
          </span>
          <h2 className="text-3xl md:text-4xl lg:text-5xl font-bold text-secondary-900 mb-4">
            {headline.replace('Services', '')}{' '}
            <span className="gradient-text">Services</span>
          </h2>
          <p className="text-lg text-secondary-600 max-w-2xl mx-auto">
            {description}
          </p>
        </motion.div>

        {/* Services Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {services.map((service, index) => {
            const colors = colorVariants[service.color as keyof typeof colorVariants]
            const IconComponent = iconMap[service.icon] || Users
            return (
              <motion.div
                key={service.title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1 }}
                className="group"
              >
                <Link href={`/#${service.id}`}>
                  <div className={`card h-full ${colors.hover} transition-all duration-300`}>
                    {/* Icon */}
                    <div className={`w-14 h-14 rounded-xl ${colors.icon} flex items-center justify-center mb-4`}>
                      <IconComponent size={28} />
                    </div>

                    {/* Content */}
                    <h3 className="text-xl font-bold text-secondary-900 mb-3 group-hover:text-primary-600 transition-colors">
                      {service.title}
                    </h3>
                    <p className="text-secondary-600 mb-4">
                      {service.description}
                    </p>

                    {/* Features */}
                    <div className="flex flex-wrap gap-2 mb-4">
                      {service.features.map((feature) => (
                        <span
                          key={feature}
                          className={`px-3 py-1 ${colors.badge} text-xs font-medium rounded-full`}
                        >
                          {feature}
                        </span>
                      ))}
                    </div>

                    {/* Learn More */}
                    <div className="flex items-center text-primary-600 font-medium text-sm mt-auto pt-4 border-t border-secondary-100">
                      Learn More
                      <ArrowRight size={16} className="ml-2 group-hover:translate-x-2 transition-transform" />
                    </div>
                  </div>
                </Link>
              </motion.div>
            )
          })}
        </div>

        {/* CTA */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mt-12"
        >
          <Link href="/#book" className="btn-primary inline-flex">
            Get a Custom Quote
            <ArrowRight size={18} className="ml-2" />
          </Link>
        </motion.div>
      </div>
    </section>
  )
}
