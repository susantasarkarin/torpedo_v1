/**
 * Why Join Page
 * Marketing page explaining benefits of joining the survey panel
 */

import { Link } from 'react-router-dom';
import '../styles/panel.css';

export default function WhyJoin() {
  const benefits = [
    {
      icon: '🎯',
      title: 'Voice Your Opinion',
      description: 'Share your thoughts on products, services, and brands that matter to you.'
    },
    {
      icon: '📱',
      title: 'Take Surveys Anywhere',
      description: 'Complete surveys on any device - mobile, tablet, or desktop.'
    },
    {
      icon: '💰',
      title: 'Earn Reward Points',
      description: 'Get paid for every survey you complete. The more you participate, the more you earn.'
    },
    {
      icon: '🎁',
      title: 'Redeem Great Prizes',
      description: 'Exchange your points for gift cards, cash via PayPal/UPI, or donate to charity.'
    },
    {
      icon: '🔒',
      title: 'GDPR Compliant',
      description: 'Your data is secure. We never sell your personal information to third parties.'
    },
    {
      icon: '⚡',
      title: 'Quick & Easy',
      description: 'Most surveys take only 5-15 minutes. Earn during your coffee break!'
    }
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Hero Section */}
      <section className="panel-hero-bg py-20">
        <div className="max-w-4xl mx-auto px-6 text-center text-white relative z-10">
          <h1 className="text-4xl md:text-5xl font-bold mb-4">
            Express your views and earn points!
          </h1>
          <p className="text-xl text-white/80 mb-8">
            Join thousands of panelists who share their opinions and get rewarded.
          </p>
          <Link to="/panel/signup" className="panel-btn-accent text-lg px-8 py-4">
            Join Now - It's FREE!
          </Link>
        </div>
      </section>

      {/* Benefits Section */}
      <section className="py-16 px-6">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-800 mb-12">
            Why Join Our Panel?
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {benefits.map((benefit, index) => (
              <div key={index} className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
                <div className="text-4xl mb-4">{benefit.icon}</div>
                <h3 className="text-lg font-semibold text-gray-800 mb-2">{benefit.title}</h3>
                <p className="text-gray-600">{benefit.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-16 px-6 bg-white">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-gray-800 mb-12">How It Works</h2>
          <div className="flex flex-col md:flex-row items-center justify-center gap-8">
            <div className="flex flex-col items-center">
              <div className="w-20 h-20 rounded-full bg-panel-primary text-white flex items-center justify-center text-2xl font-bold mb-4">1</div>
              <h3 className="font-semibold text-gray-800 mb-1">Sign Up</h3>
              <p className="text-gray-600 text-sm">Create your free account</p>
            </div>
            <div className="hidden md:block text-4xl text-gray-300">→</div>
            <div className="flex flex-col items-center">
              <div className="w-20 h-20 rounded-full bg-panel-primary text-white flex items-center justify-center text-2xl font-bold mb-4">2</div>
              <h3 className="font-semibold text-gray-800 mb-1">Complete Surveys</h3>
              <p className="text-gray-600 text-sm">Share your valuable opinions</p>
            </div>
            <div className="hidden md:block text-4xl text-gray-300">→</div>
            <div className="flex flex-col items-center">
              <div className="w-20 h-20 rounded-full bg-panel-accent text-white flex items-center justify-center text-2xl font-bold mb-4">3</div>
              <h3 className="font-semibold text-gray-800 mb-1">Get Paid</h3>
              <p className="text-gray-600 text-sm">Redeem points for rewards</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-16 px-6 bg-panel-primary">
        <div className="max-w-3xl mx-auto text-center text-white">
          <h2 className="text-3xl font-bold mb-4">Ready to Start Earning?</h2>
          <p className="text-white/80 mb-8">
            Join our panel today and get a sign-up bonus!
          </p>
          <Link to="/panel/signup" className="panel-btn-accent text-lg px-8 py-4">
            Create Free Account
          </Link>
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
        <p className="text-white/50 text-sm">© {new Date().getFullYear()} Survey Fieldwork. All rights reserved.</p>
      </footer>
    </div>
  );
}
