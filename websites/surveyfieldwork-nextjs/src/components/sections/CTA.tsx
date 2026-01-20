'use client'

import { motion } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, Sparkles } from 'lucide-react'
import { ctaContent as defaultContent } from '@/lib/content'

interface CTAProps {
  content?: typeof defaultContent
}

export default function CTA({ content = defaultContent }: CTAProps) {
  const { badge, title, titleHighlight, description, primaryCta, secondaryCta, stats } = content
  
  return (
    <section className="py-24 relative overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary-600 via-primary-700 to-accent-700" />
      
      {/* Decorations */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-24 -right-24 w-96 h-96 bg-white/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-96 h-96 bg-accent-500/20 rounded-full blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-white/5 rounded-full" />
      </div>

      <div className="container-custom relative z-10">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center max-w-3xl mx-auto"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-white/10 backdrop-blur-sm rounded-full text-white/90 text-sm font-medium mb-6">
            <Sparkles size={16} />
            {badge}
          </div>

          <h2 className="text-3xl md:text-4xl lg:text-5xl font-bold text-white mb-6">
            {title}{' '}
            <span className="text-accent-300">{titleHighlight}</span>
          </h2>

          <p className="text-lg md:text-xl text-white/80 mb-8">
            {description}
          </p>

          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              href={primaryCta.href}
              className="inline-flex items-center justify-center px-8 py-4 bg-white text-primary-700 font-semibold rounded-full hover:bg-white/90 transition-colors group"
            >
              {primaryCta.text}
              <ArrowRight size={18} className="ml-2 group-hover:translate-x-1 transition-transform" />
            </Link>
            <Link
              href={secondaryCta.href}
              className="inline-flex items-center justify-center px-8 py-4 bg-transparent text-white font-semibold rounded-full border-2 border-white/30 hover:bg-white/10 transition-colors"
            >
              {secondaryCta.text}
            </Link>
          </div>

          {/* Trust Indicators */}
          <div className="mt-12 flex flex-wrap justify-center gap-8 text-white/60">
            {stats.map((stat) => (
              <div key={stat.label} className="flex items-center gap-2">
                <span className="text-2xl font-bold text-white">{stat.value}</span>
                <span>{stat.label}</span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}
