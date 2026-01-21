'use client'

import { motion } from 'framer-motion'
import Image from 'next/image'
import Link from 'next/link'
import { CheckSquare } from 'lucide-react'

export default function JoinPanel() {
    return (
        <section className="py-20 bg-white">
            <div className="container-custom">
                {/* Main Heading */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true }}
                    className="text-center mb-12"
                >
                    <h2 className="text-3xl md:text-4xl lg:text-5xl font-bold text-[#0000cc] mb-4">
                        Want To Earn Money With Surveys?
                    </h2>
                    <p className="text-xl md:text-2xl text-[#0f172a]">
                        Join <span className="font-bold">Survey Fieldwork Panel</span> Now!
                    </p>
                </motion.div>

                {/* Content Card */}
                <div className="bg-white rounded-[2rem] shadow-[0_10px_40px_-10px_rgba(0,0,0,0.1)] overflow-hidden max-w-5xl mx-auto border border-gray-100">
                    <div className="grid md:grid-cols-2">
                        {/* Left Content */}
                        <div className="p-8 md:p-12 lg:p-16 flex flex-col justify-center">
                            <h3 className="text-3xl md:text-4xl font-bold text-[#0f172a] mb-8">
                                How it works?
                            </h3>

                            <ul className="space-y-6 mb-10">
                                <li className="flex items-start gap-3">
                                    <div className="mt-1 bg-[#4ade80] rounded text-white p-0.5">
                                        <CheckSquare size={18} fill="white" className="text-[#4ade80]" />
                                    </div>
                                    <span className="text-lg text-[#334155]">Become our community panel member</span>
                                </li>
                                <li className="flex items-start gap-3">
                                    <div className="mt-1 bg-[#4ade80] rounded text-white p-0.5">
                                        <CheckSquare size={18} fill="white" className="text-[#4ade80]" />
                                    </div>
                                    <span className="text-lg text-[#334155]">Let your opinion make a difference</span>
                                </li>
                                <li className="flex items-start gap-3">
                                    <div className="mt-1 bg-[#4ade80] rounded text-white p-0.5">
                                        <CheckSquare size={18} fill="white" className="text-[#4ade80]" />
                                    </div>
                                    <span className="text-lg text-[#334155]">Get rewarded for your participation</span>
                                </li>
                            </ul>

                            <div className="space-y-4">
                                <Link
                                    href="https://panel.surveyfieldwork.com/register"
                                    className="inline-block px-8 py-3 bg-[#2563eb] text-white text-lg font-semibold rounded shadow-lg hover:bg-[#1d4ed8] transition-colors text-center"
                                >
                                    Register Now
                                </Link>
                                <p className="text-red-500 italic text-sm font-medium">
                                    Signup bonus 10 points.. hurry!
                                </p>
                            </div>
                        </div>

                        {/* Right Image */}
                        <div className="relative h-[400px] md:h-auto overflow-hidden bg-gray-100">
                            {/* Use the reference image visual */}
                            <div className="absolute inset-0 flex items-center justify-center">
                                <Image
                                    src="/assets/images/join-panel-mobile.png"
                                    alt="Join Panel Mobile App"
                                    width={600}
                                    height={800}
                                    className="object-cover w-full h-full"
                                    // Fallback for visual representation if image missing
                                    onError={(e) => {
                                        e.currentTarget.style.display = 'none';
                                        e.currentTarget.parentElement?.classList.add('fallback-app-visual');
                                    }}
                                />

                                {/* Fallback Visual mimicking the reference */}
                                <div className="hidden fallback-app-visual w-full h-full bg-gradient-to-r from-gray-200 to-gray-300 relative flex items-center justify-center">
                                    <div className="w-1/2 h-4/5 bg-black rounded-[2rem] border-[8px] border-black overflow-hidden shadow-2xl relative z-10">
                                        <div className="w-full h-full bg-[#008080] flex flex-col items-center justify-center text-white p-4 text-center">
                                            <div className="mb-4">YOU'VE EARNED A REWARD!</div>
                                            <div className="w-16 h-16 bg-white/20 rounded-full mb-4 flex items-center justify-center">🎁</div>
                                            <button className="bg-white/20 px-4 py-2 rounded text-xs mt-4">REDEEM REWARD</button>
                                        </div>
                                    </div>
                                    {/* Hand holding phone simulation */}
                                    <div className="absolute bottom-0 right-0 w-2/3 h-1/2 bg-[#f0d5c0] rounded-tl-[100px] z-0 opacity-80"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    )
}
