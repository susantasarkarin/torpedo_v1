'use client'

import { motion } from 'framer-motion'

export default function EnterpriseSolutions() {
    return (
        <section className="py-24 bg-white relative overflow-hidden">
            {/* Background Decoration matching reference (subtle gradient/shape) */}
            <div className="absolute top-0 right-0 w-2/3 h-full bg-gradient-radial from-blue-50/50 to-transparent opacity-60 pointer-events-none transform translate-x-1/4" />

            <div className="container-custom relative z-10">
                <div className="max-w-4xl">
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        whileInView={{ opacity: 1, y: 0 }}
                        viewport={{ once: true }}
                        className="mb-10"
                    >
                        <h2 className="text-3xl md:text-4xl font-bold text-[#0f172a] mb-8">
                            Enterprise Solutions
                        </h2>

                        <div className="space-y-6 text-gray-600 leading-relaxed text-[15px] md:text-base">
                            <p>
                                Survey Fieldwork's platform is designed to simplify your data collection process and help you achieve your research goals in a single interface. No more dealing with multiple sample vendors or self service tools - access everything you need through our enterprise grade solutions.
                            </p>

                            <p>
                                With our platform, you can access our proprietary panel, create standardized processes, and regulate workflows across your supply sources. Say goodbye to manual steps and hello to increased efficiency, allowing your teams to focus on more important tasks. You can manage end-to-end ordering, sampling, and project management operations from one user interface or API, ensuring faster quoting, project delivery, and simplified financial reconciliation processes.
                            </p>

                            <p>
                                Survey Fieldwork Enterprise solutions offer the option to create personalized technology products within one powerful API. You can integrate your existing tech stack with our feature-rich APIs, leveraging continuous digital and data innovations. You can also access an ecosystem of Data Solutions and market research technology providers to accelerate your competition in the market.
                            </p>

                            <p>
                                Our Partner Success and Tech Support teams deliver end-to-end support and enterprise-grade maintenance SLAs. You can transform and accelerate your research processes, achieve step-changes in delivery speed and operational efficiency, and lay a foundation for accelerated innovation. Gain operational insights using Business Intelligence tools. Choose Survey Fieldwork for world class service and expertise in research automation. Simplify your market research solutions and achieve your research goals with our powerful platform.
                            </p>
                        </div>
                    </motion.div>
                </div>
            </div>
        </section>
    )
}
