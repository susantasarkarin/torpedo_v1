/**
 * Privacy Policy Page
 * Data protection and privacy information for panelists
 */

import { Link } from 'react-router-dom';
import '../styles/panel.css';

export default function Privacy() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="bg-panel-primary text-white py-6">
        <div className="max-w-4xl mx-auto px-6">
          <Link to="/panel/login" className="inline-flex items-center gap-2 mb-4">
            <span className="text-2xl font-bold">
              Sur<span className="text-panel-accent">v</span>ey
            </span>
            <span className="bg-white/20 text-white text-xs font-bold px-2 py-0.5 rounded">
              FIELDWORK
            </span>
          </Link>
          <h1 className="text-3xl font-bold">Privacy Policy</h1>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8">
          <p className="text-gray-600 mb-6">Last updated: January 2026</p>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">1. Data We Collect</h2>
            <p className="text-gray-600 mb-3">We collect the following types of information:</p>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li><strong>Identity Data:</strong> Name, date of birth, gender</li>
              <li><strong>Contact Data:</strong> Email address, phone number, address</li>
              <li><strong>Profile Data:</strong> Education, occupation, income range, interests</li>
              <li><strong>Survey Data:</strong> Responses to survey questions</li>
              <li><strong>Technical Data:</strong> IP address, browser type, device information</li>
              <li><strong>Transaction Data:</strong> Reward points earned and redeemed</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">2. How We Use Your Data</h2>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li>To match you with relevant surveys based on your profile</li>
              <li>To process your reward redemptions</li>
              <li>To improve our services and user experience</li>
              <li>To prevent fraud and maintain platform security</li>
              <li>To send you notifications about new surveys and rewards</li>
              <li>To comply with legal obligations</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">3. Data Sharing</h2>
            <p className="text-gray-600 mb-3">
              We share your survey responses with our research clients in <strong>anonymized or aggregated form only</strong>. Your personal identity is never revealed to survey sponsors.
            </p>
            <p className="text-gray-600">
              We do not sell your personal information to third parties for marketing purposes.
            </p>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">4. GDPR Compliance (EU Users)</h2>
            <p className="text-gray-600 mb-3">If you are in the European Union, you have the right to:</p>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li><strong>Access:</strong> Request a copy of your personal data</li>
              <li><strong>Rectification:</strong> Correct inaccurate personal data</li>
              <li><strong>Erasure:</strong> Request deletion of your personal data</li>
              <li><strong>Portability:</strong> Receive your data in a portable format</li>
              <li><strong>Objection:</strong> Object to processing of your personal data</li>
              <li><strong>Restriction:</strong> Request restriction of processing</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">5. CCPA Compliance (California Residents)</h2>
            <p className="text-gray-600 mb-3">California residents have the right to:</p>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li>Know what personal information we collect and how it's used</li>
              <li>Request deletion of personal information</li>
              <li>Opt-out of the sale of personal information (we do not sell your data)</li>
              <li>Non-discrimination for exercising your privacy rights</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">6. Data Retention</h2>
            <p className="text-gray-600">
              We retain your personal data for as long as your account is active. If you request account deletion, we will delete your data within 30 days, except where we are required to retain it for legal or compliance purposes.
            </p>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">7. Cookies</h2>
            <p className="text-gray-600">
              We use cookies and similar technologies to enhance your experience, analyze usage, and assist with surveys. You can manage cookie preferences in your browser settings.
            </p>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">8. Security</h2>
            <p className="text-gray-600">
              We implement industry-standard security measures including encryption, secure servers, and regular security audits to protect your personal information.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-gray-800 mb-3">9. Contact Us</h2>
            <p className="text-gray-600">
              For privacy-related inquiries or to exercise your data rights, contact us at{' '}
              <a href="mailto:privacy@surveyfieldwork.com" className="text-panel-primary hover:underline">
                privacy@surveyfieldwork.com
              </a>
            </p>
          </section>
        </div>

        {/* Back Link */}
        <div className="mt-8 text-center">
          <Link to="/panel/login" className="text-panel-primary hover:underline">
            ← Back to Login
          </Link>
        </div>
      </main>
    </div>
  );
}
