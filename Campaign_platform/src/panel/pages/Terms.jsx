/**
 * Terms and Conditions Page
 * Legal terms for survey panel membership
 */

import { Link } from 'react-router-dom';
import '../styles/panel.css';

export default function Terms() {
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
          <h1 className="text-3xl font-bold">Terms & Conditions</h1>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8">
          <p className="text-gray-600 mb-6">Last updated: January 2026</p>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">1. Registration Requirements</h2>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li>You must be at least 18 years old to register as a panelist.</li>
              <li>You must provide a valid email address for account verification.</li>
              <li>Only one account per person is allowed. Multiple accounts will be terminated.</li>
              <li>All information provided must be accurate and up-to-date.</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">2. ID Verification</h2>
            <p className="text-gray-600 mb-3">
              When your earnings reach ₹10,000 (or equivalent), you may be required to verify your identity before redeeming rewards. This is to prevent fraud and ensure compliance with financial regulations.
            </p>
            <p className="text-gray-600">
              Acceptable forms of ID include government-issued photo ID (Aadhaar, Passport, PAN Card, Voter ID).
            </p>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">3. Prohibited Countries</h2>
            <p className="text-gray-600 mb-3">
              Due to legal and compliance requirements, residents of certain countries may not be eligible to participate. Please check your eligibility during registration.
            </p>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">4. Rules & Restrictions</h2>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li>Answer all survey questions honestly and thoughtfully.</li>
              <li>Do not use VPNs, proxies, or other tools to manipulate your location.</li>
              <li>Do not share your account credentials with others.</li>
              <li>Do not attempt to complete the same survey multiple times.</li>
              <li>Do not use automated tools or bots to complete surveys.</li>
              <li>Quality checks are embedded in surveys - failing these may result in disqualification.</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">5. Rewards & Redemption</h2>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li>Reward points have no expiry date.</li>
              <li>Minimum redemption threshold is ₹100.</li>
              <li>Redemption requests are processed within 3-5 business days.</li>
              <li>Available redemption options include Amazon/Flipkart gift cards, PayPal, and UPI transfers.</li>
              <li>We reserve the right to cancel points earned through fraudulent activity.</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">6. Account Termination</h2>
            <p className="text-gray-600 mb-3">
              We reserve the right to suspend or terminate your account if you:
            </p>
            <ul className="list-disc pl-6 text-gray-600 space-y-2">
              <li>Violate any of these terms and conditions.</li>
              <li>Provide false or misleading information.</li>
              <li>Engage in fraudulent activity.</li>
              <li>Have been inactive for more than 12 months.</li>
            </ul>
          </section>

          <section className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-3">7. Changes to Terms</h2>
            <p className="text-gray-600">
              We may update these terms from time to time. Continued use of our services after changes constitutes acceptance of the new terms. We will notify you of significant changes via email.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-gray-800 mb-3">8. Contact Us</h2>
            <p className="text-gray-600">
              If you have questions about these terms, please contact us at{' '}
              <a href="mailto:support@surveyfieldwork.com" className="text-panel-primary hover:underline">
                support@surveyfieldwork.com
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
