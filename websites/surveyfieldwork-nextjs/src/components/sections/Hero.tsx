'use client'

import { motion } from 'framer-motion'
import Link from 'next/link'
import Image from 'next/image'
import { ArrowRight, CheckCircle, Play } from 'lucide-react'
import { heroContent as defaultContent } from '@/lib/content'

interface HeroProps {
  content?: typeof defaultContent
}

export default function Hero({ content = defaultContent }: HeroProps) {
  const { badges, headline, subheadline, primaryCta, secondaryCta, stats } = content
  
  // Parse headline to add gradient styling
  const formattedHeadline = headline.replace(
    /(Data|Strategy)/g, 
    '<span class="gradient-text">$1</span>'
  )

  return (
    <section className="relative min-h-screen flex items-center pt-20 overflow-hidden bg-gradient-to-br from-secondary-50 via-white to-primary-50/30">
      {/* Background Decorations */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-24 -right-24 w-96 h-96 bg-primary-500/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-48 -left-48 w-[600px] h-[600px] bg-accent-500/10 rounded-full blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-gradient-radial from-primary-100/50 to-transparent rounded-full" />
      </div>

      <div className="container-custom relative z-10">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Content */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-center lg:text-left"
          >
            {/* Trust Badges */}
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="flex flex-wrap justify-center lg:justify-start gap-3 mb-6"
            >
              {badges.map((badge) => (
                <span
                  key={badge}
                  className="inline-flex items-center gap-1.5 px-3 py-1 bg-primary-100 text-primary-700 text-sm font-medium rounded-full"
                >
                  <CheckCircle size={14} />
                  {badge}
                </span>
              ))}
            </motion.div>

            <h1 
              className="text-4xl md:text-5xl lg:text-6xl font-bold text-secondary-900 leading-tight mb-6"
              dangerouslySetInnerHTML={{ __html: formattedHeadline }}
            />

            <p className="text-lg md:text-xl text-secondary-600 mb-8 max-w-xl mx-auto lg:mx-0">
              {subheadline}
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start mb-8">
              <Link href={primaryCta.href} className="btn-primary group">
                {primaryCta.label}
                <ArrowRight size={18} className="ml-2 group-hover:translate-x-1 transition-transform" />
              </Link>
              <Link href={secondaryCta.href} className="btn-outline group">
                <Play size={18} className="mr-2" />
                {secondaryCta.label}
              </Link>
            </div>

            {/* Stats */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="grid grid-cols-3 gap-6 pt-8 border-t border-secondary-200"
            >
              {stats.map((stat) => (
                <div key={stat.label} className="text-center lg:text-left">
                  <div className="text-2xl md:text-3xl font-bold gradient-text">{stat.value}</div>
                  <div className="text-sm text-secondary-500">{stat.label}</div>
                </div>
              ))}
            </motion.div>
          </motion.div>

          {/* Image / Visual */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="relative hidden lg:block"
          >
            <div className="relative w-full aspect-square max-w-lg mx-auto">
              {/* Main Image */}
              <div className="absolute inset-0 bg-gradient-to-br from-primary-500 to-accent-500 rounded-3xl rotate-3 opacity-20" />
              <div className="relative bg-white rounded-3xl shadow-hard overflow-hidden">
                <Image
                  src="/assets/images/hero-visual.png"
                  alt="Data Analytics Dashboard"
                  width={600}
                  height={600}
                  className="w-full h-full object-cover"
                  priority
                />
              </div>

              {/* Floating Cards */}
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.6 }}
                className="absolute -left-8 top-1/4 bg-white rounded-xl shadow-medium p-4 flex items-center gap-3"
              >
                <div className="w-12 h-12 bg-accent-100 rounded-lg flex items-center justify-center">
                  <span className="text-2xl">📊</span>
                </div>
                <div>
                  <div className="text-sm font-medium text-secondary-900">Real-time Analytics</div>
                  <div className="text-xs text-secondary-500">Live data insights</div>
                </div>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.8 }}
                className="absolute -right-8 bottom-1/4 bg-white rounded-xl shadow-medium p-4 flex items-center gap-3"
              >
                <div className="w-12 h-12 bg-primary-100 rounded-lg flex items-center justify-center">
                  <span className="text-2xl">🎯</span>
                </div>
                <div>
                  <div className="text-sm font-medium text-secondary-900">Targeted Sampling</div>
                  <div className="text-xs text-secondary-500">Quality respondents</div>
                </div>
              </motion.div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* Scroll Indicator */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2"
      >
        <div className="w-6 h-10 border-2 border-secondary-300 rounded-full flex justify-center">
          <motion.div
            animate={{ y: [0, 12, 0] }}
            transition={{ repeat: Infinity, duration: 1.5 }}
            className="w-1.5 h-3 bg-primary-500 rounded-full mt-2"
          />
        </div>
      </motion.div>
    </section>
  )
}
