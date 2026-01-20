'use client'

import { motion } from 'framer-motion'
import Image from 'next/image'
import Link from 'next/link'
import { CheckCircle, Award, Globe, Users, ArrowRight } from 'lucide-react'
import { aboutContent as defaultContent } from '@/lib/content'

const iconMap: Record<string, React.ElementType> = {
  Globe,
  Users,
  Award,
}

interface AboutProps {
  content?: typeof defaultContent
}

export default function About({ content = defaultContent }: AboutProps) {
  const { badge, title, titleHighlight, description, highlights, features, cta, image } = content
  return (
    <section id="about" className="section-padding bg-secondary-50">
      <div className="container-custom">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Left - Image/Visual */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="relative"
          >
            <div className="relative aspect-square max-w-lg mx-auto">
              {/* Background Decoration */}
              <div className="absolute inset-0 bg-gradient-to-br from-primary-500 to-accent-500 rounded-3xl -rotate-3 opacity-20" />
              
              {/* Main Image */}
              <div className="relative bg-white rounded-3xl shadow-hard overflow-hidden z-10">
                <Image
                  src="/assets/images/about-team.jpg"
                  alt="Survey Fieldwork Team"
                  width={500}
                  height={500}
                  className="w-full h-full object-cover"
                />
              </div>

              {/* Stats Cards */}
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ delay: 0.3 }}
                className="absolute -bottom-6 -right-6 bg-white rounded-2xl shadow-medium p-6 z-20"
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-accent-100 rounded-xl flex items-center justify-center">
                    <Award className="text-accent-600" size={24} />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-secondary-900">500+</div>
                    <div className="text-sm text-secondary-500">Projects Completed</div>
                  </div>
                </div>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ delay: 0.4 }}
                className="absolute -top-6 -left-6 bg-white rounded-2xl shadow-medium p-6 z-20"
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-primary-100 rounded-xl flex items-center justify-center">
                    <Users className="text-primary-600" size={24} />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-secondary-900">98%</div>
                    <div className="text-sm text-secondary-500">Client Satisfaction</div>
                  </div>
                </div>
              </motion.div>
            </div>
          </motion.div>

          {/* Right - Content */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
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
            <p className="text-lg text-secondary-600 mb-6">
              {description.primary}
            </p>
            <p className="text-secondary-600 mb-8">
              {description.secondary}
            </p>

            {/* Features Grid */}
            <div className="grid sm:grid-cols-2 gap-3 mb-8">
              {features.map((feature) => (
                <div key={feature} className="flex items-center gap-2">
                  <CheckCircle className="text-accent-500 flex-shrink-0" size={20} />
                  <span className="text-secondary-700">{feature}</span>
                </div>
              ))}
            </div>

            {/* CTA */}
            <div className="flex flex-wrap gap-4">
              <Link href={cta.primary.href} className="btn-primary">
                {cta.primary.text}
                <ArrowRight size={18} className="ml-2" />
              </Link>
              <Link href={cta.secondary.href} className="btn-outline">
                {cta.secondary.text}
              </Link>
            </div>
          </motion.div>
        </div>

        {/* Highlights Bar */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="mt-16 grid grid-cols-3 gap-6"
        >
          {highlights.map((item) => {
            const IconComponent = iconMap[item.icon] || Globe
            return (
              <div 
                key={item.label}
                className="bg-white rounded-2xl p-6 shadow-soft text-center"
              >
                <div className="w-14 h-14 bg-primary-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                  <IconComponent className="text-primary-600" size={28} />
                </div>
                <div className="text-3xl font-bold gradient-text mb-1">{item.value}</div>
                <div className="text-secondary-500">{item.label}</div>
              </div>
            )
          })}
        </motion.div>
      </div>
    </section>
  )
}
