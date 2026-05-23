/**
 * Rewards Info Page
 * Marketing page about the rewards program
 */

import { Link } from 'react-router-dom';
import '../styles/panel.css';

export default function RewardsInfo() {
  return (
    <div className="min-h-screen bg-background">
      {/* Hero Section */}
      <section className="panel-hero-bg py-20">
        <div className="max-w-4xl mx-auto px-6 text-center text-white relative z-10">
          <h1 className="text-4xl md:text-5xl font-bold mb-4">
            Your Opinion Matters and Earns Rewards!
          </h1>
          <p className="text-xl text-white/80 mb-8">
            Complete surveys and exchange your points for amazing rewards.
          </p>
        </div>
      </section>

      {/* How Rewards Work */}
      <section className="py-16 px-6">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-800 mb-12">
            How Our Rewards Program Works
          </h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-full bg-panel-primary-100 flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6 text-panel-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-gray-800 mb-1">Earn Points</h3>
                <p className="text-gray-600">Complete surveys to earn reward points. Longer surveys = more points!</p>
              </div>
            </div>
            
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-full bg-panel-accent-100 flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6 text-panel-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-gray-800 mb-1">1 Point = ₹1</h3>
                <p className="text-gray-600">Simple conversion. No complicated calculations or hidden fees.</p>
              </div>
            </div>
            
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-full bg-panel-success-100 flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6 text-panel-success" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-gray-800 mb-1">No Expiry</h3>
                <p className="text-gray-600">Your points never expire as long as your account is active.</p>
              </div>
            </div>
            
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-gray-800 mb-1">Fast Redemption</h3>
                <p className="text-gray-600">Redeem in 3-5 business days. Digital rewards even faster!</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Reward Options */}
      <section className="py-16 px-6 bg-white">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-800 mb-12">
            Redemption Options
          </h2>
          
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <div className="text-center">
              <div className="w-20 h-20 mx-auto bg-orange-100 rounded-xl flex items-center justify-center mb-3">
                <span className="text-4xl">🎁</span>
              </div>
              <p className="font-medium text-gray-800">Amazon</p>
              <p className="text-sm text-gray-500">Gift Cards</p>
            </div>
            
            <div className="text-center">
              <div className="w-20 h-20 mx-auto bg-blue-100 rounded-xl flex items-center justify-center mb-3">
                <span className="text-4xl">🛒</span>
              </div>
              <p className="font-medium text-gray-800">Flipkart</p>
              <p className="text-sm text-gray-500">Gift Cards</p>
            </div>
            
            <div className="text-center">
              <div className="w-20 h-20 mx-auto bg-indigo-100 rounded-xl flex items-center justify-center mb-3">
                <span className="text-4xl">💳</span>
              </div>
              <p className="font-medium text-gray-800">PayPal</p>
              <p className="text-sm text-gray-500">Cash Transfer</p>
            </div>
            
            <div className="text-center">
              <div className="w-20 h-20 mx-auto bg-green-100 rounded-xl flex items-center justify-center mb-3">
                <span className="text-4xl">📱</span>
              </div>
              <p className="font-medium text-gray-800">UPI</p>
              <p className="text-sm text-gray-500">Direct Transfer</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-16 px-6 bg-panel-primary">
        <div className="max-w-3xl mx-auto text-center text-white">
          <h2 className="text-3xl font-bold mb-4">Ready to Start Earning?</h2>
          <p className="text-white/80 mb-8">
            Join now and get a welcome bonus on your first completed survey!
          </p>
          <Link to="/panel/signup" className="panel-btn-accent text-lg px-8 py-4">
            Join Now - It's FREE!
          </Link>
        </div>
      </section>

      {/* Contact */}
      <section className="py-12 px-6 bg-gray-50">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-gray-600">
            Have questions about rewards? Contact us at{' '}
            <a href="mailto:rewards@cogentixresearch.com" className="text-panel-primary hover:underline">
              rewards@cogentixresearch.com
            </a>
          </p>
        </div>
      </section>

      {/* Footer */}
      <footer className="panel-footer">
        <nav className="mb-4">
          <Link to="/panel/login">Login</Link>
          <Link to="/panel/signup">Sign Up</Link>
          <Link to="/panel/terms">Terms</Link>
          <Link to="/panel/privacy">Privacy</Link>
          <Link to="/panel/faq">FAQ</Link>
        </nav>
        <p className="text-white/50 text-sm">© {new Date().getFullYear()} Cogentix Research. All rights reserved.</p>
      </footer>
    </div>
  );
}
