'use client'

import { motion } from 'framer-motion'
import Link from 'next/link'
import { CheckCircle } from 'lucide-react'
import { heroContent as defaultContent } from '@/lib/content'

interface HeroProps {
  content?: typeof defaultContent
}

export default function Hero({ content = defaultContent }: HeroProps) {
  const badges = ['Trusted', 'Experienced', 'Professional']

  return (
    <section className="relative min-h-[90vh] flex items-center overflow-hidden bg-[#2563eb]">
      {/* Gradient Background with Wave */}
      <div className="absolute inset-0">
        {/* Main gradient */}
        <div className="absolute inset-0 bg-gradient-to-br from-[#1d4ed8] via-[#2563eb] to-[#3b82f6]" />

        {/* Decorative wave shapes */}
        <svg
          className="absolute right-0 top-0 h-full w-1/2 opacity-30"
          viewBox="0 0 400 600"
          fill="none"
          preserveAspectRatio="none"
        >
          <path
            d="M100,0 Q150,150 100,300 Q50,450 100,600 L400,600 L400,0 Z"
            fill="rgba(59, 130, 246, 0.5)"
          />
        </svg>
        <svg
          className="absolute right-0 top-0 h-full w-2/5 opacity-20"
          viewBox="0 0 300 600"
          fill="none"
          preserveAspectRatio="none"
        >
          <path
            d="M50,0 Q100,200 50,400 Q0,500 50,600 L300,600 L300,0 Z"
            fill="rgba(96, 165, 250, 0.6)"
          />
        </svg>
      </div>

      <div className="container-custom relative z-10 py-20">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Content */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-left"
          >
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-white leading-tight mb-6">
              Where Data<br />
              Meets Strategy
            </h1>

            <p className="text-lg text-white/80 mb-8 max-w-lg">
              Partner with us to gain a competitive edge, seize opportunities, and drive success in your industry. Experience the power of market research and unlock your business's full potential today.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-wrap gap-4 mb-10">
              <Link
                href="/#book"
                className="inline-flex items-center justify-center px-6 py-3 bg-white text-[#2563eb] font-semibold rounded-md hover:bg-white/90 transition-all shadow-lg hover:shadow-xl"
              >
                Book Free Consultation
              </Link>
              <Link
                href="/#about"
                className="inline-flex items-center justify-center px-6 py-3 border-2 border-white text-white font-semibold rounded-md hover:bg-white/10 transition-all"
              >
                Learn More
              </Link>
            </div>

            {/* Trust Badges */}
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="flex flex-wrap gap-6"
            >
              {badges.map((badge) => (
                <div
                  key={badge}
                  className="flex items-center gap-2 text-white/90"
                >
                  <CheckCircle size={18} className="text-white" />
                  <span className="text-sm font-medium">{badge}</span>
                </div>
              ))}
            </motion.div>
          </motion.div>

          {/* Image Placeholder - Woman Image */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="relative hidden lg:flex justify-end"
          >
            <div className="relative w-full max-w-md">
              {/* Placeholder for woman image - using gradient placeholder */}
              <div className="aspect-[3/4] bg-gradient-to-b from-[#3b82f6] to-[#1d4ed8] rounded-2xl flex items-end justify-center overflow-hidden">
                {/* Decorative person silhouette placeholder */}
                <svg
                  viewBox="0 0 200 300"
                  className="w-3/4 h-3/4 text-white/20"
                  fill="currentColor"
                >
                  <ellipse cx="100" cy="60" rx="40" ry="50" />
                  <path d="M40,130 Q100,100 160,130 L180,300 L20,300 Z" />
                </svg>
              </div>

              {/* Optional: Add actual image when available */}
              {/* 
              <Image
                src="/assets/images/hero-woman.png"
                alt="Professional woman"
                width={400}
                height={600}
                className="object-contain"
                priority
              />
              */}
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  )
}

