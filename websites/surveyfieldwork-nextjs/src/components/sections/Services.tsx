'use client'

import { motion } from 'framer-motion'
import Image from 'next/image'

export default function Services() {
  return (
    <section className="py-20 bg-white overflow-hidden">
      <div className="container-custom">
        {/* Section Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-20"
        >
          <h2 className="text-4xl md:text-5xl font-bold text-[#0f172a] mb-3">
            What We Do
          </h2>
          <p className="text-xl text-gray-400 italic font-light">
            Market Analysis and Consumer Data Collection
          </p>
        </motion.div>

        {/* Audience Sampling Section */}
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          {/* Left Side - Image/Illustration */}
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="relative"
          >
            {/* Using a placeholder SVG or Image akin to the reference */}
            <div className="relative w-full aspect-[4/3] max-w-xl mx-auto">
              <div className="absolute inset-0 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-3xl -z-10 transform -rotate-3" />
              <Image
                src="/assets/images/audience-sampling.png"
                alt="Audience Sampling Illustration"
                width={600}
                height={450}
                className="w-full h-full object-contain"
                // Fallback to a constructed SVG if image missing
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                  e.currentTarget.parentElement?.classList.add('fallback-svg-container');
                }}
              />
              {/* Fallback visual if image load fails (simulating the reference graphic) */}
              <div className="hidden fallback-svg-container absolute inset-0 items-center justify-center">
                <div className="grid grid-cols-2 gap-4 w-full h-full p-8">
                  <div className="bg-white shadow-lg rounded-xl p-4 flex flex-col gap-2">
                    <div className="h-2 w-1/2 bg-gray-200 rounded"></div>
                    <div className="h-2 w-3/4 bg-gray-100 rounded"></div>
                    <div className="h-20 bg-blue-50 rounded mt-2"></div>
                  </div>
                  <div className="bg-white shadow-lg rounded-xl p-4 flex flex-col gap-2 mt-8">
                    <div className="flex gap-2 mb-2">
                      <div className="w-8 h-8 rounded-full bg-blue-100"></div>
                      <div className="flex-1 space-y-1">
                        <div className="h-2 w-full bg-gray-100 rounded"></div>
                        <div className="h-2 w-2/3 bg-gray-100 rounded"></div>
                      </div>
                    </div>
                    <div className="h-16 bg-gray-50 rounded"></div>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>

          {/* Right Side - Content */}
          <motion.div
            initial={{ opacity: 0, x: 50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="space-y-6"
          >
            <h3 className="text-3xl font-bold text-[#0f172a]">
              Audience Sampling
            </h3>

            <p className="text-gray-600 leading-relaxed">
              Our customer and B2B panels power thousands of research projects for some of the world's most renowned brands. We are pioneers in sampling and are able to find niche, quality audiences across the globe.
            </p>

            <div className="space-y-6 pt-4">
              <div>
                <h4 className="font-semibold text-secondary-900 mb-2">The Survey Fieldwork Difference</h4>
                <p className="text-sm text-gray-600 leading-relaxed">
                  B2B, B2C and Longitudinal Tracker Expertise. With millions of engaged survey participants worldwide, we specialize in providing insights in hard-to-reach demographics or firmographics from anywhere around the globe with a flexible dedicated project management team.
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-secondary-900 mb-2">Faster Answers</h4>
                <p className="text-sm text-gray-600 leading-relaxed">
                  Our ingenuity and agile approach to sampling delivers quicker turnarounds so you can make better-informed decisions about the future of your business.
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-secondary-900 mb-2">Quality You Can Count On</h4>
                <p className="text-sm text-gray-600 leading-relaxed">
                  Data quality is priceless, so we are consistently working to strengthen our quality methods. Our project teams are trained in quality data best practices and fraud detection and are transparent if something goes wrong, providing creative solutions along the way.
                </p>
              </div>
            </div>

            {/* Cyan button or similar if needed, keeping it clean for now as per ref image which shows text mainly */}
            <div className="pt-4">
              <div className="h-1.5 w-24 bg-[#0ea5e9] rounded-full"></div>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  )
}

