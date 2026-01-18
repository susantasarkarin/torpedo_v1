/**
 * FAQ Page
 * Frequently asked questions about the survey panel
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import '../styles/panel.css';

const faqData = [
  {
    category: 'Account Information',
    questions: [
      {
        q: 'How do I join the panel?',
        a: 'Simply click "Sign Up" on our website and fill in your details. Registration is free and takes less than 2 minutes.'
      },
      {
        q: 'Can I have multiple accounts?',
        a: 'No, each person is allowed only one account. Multiple accounts will be detected and terminated, and any earned points will be forfeited.'
      },
      {
        q: 'How do I edit my profile?',
        a: 'Log in to your account and click on "Profile" in the navigation menu. You can update your personal information, preferences, and demographics there.'
      },
      {
        q: 'Why should I complete my profile?',
        a: 'A complete profile helps us match you with relevant surveys. The more complete your profile, the more survey invitations you\'ll receive!'
      },
    ]
  },
  {
    category: 'Surveys & Participation',
    questions: [
      {
        q: 'How do I receive survey invitations?',
        a: 'Available surveys are displayed on your dashboard when you log in. You may also receive email notifications for new surveys that match your profile.'
      },
      {
        q: 'Why do I sometimes get disqualified from surveys?',
        a: 'Surveys target specific demographics. If your profile doesn\'t match the target audience, you may be screened out. Don\'t worry - this doesn\'t affect your account negatively.'
      },
      {
        q: 'How long do surveys take?',
        a: 'Most surveys take 5-20 minutes. The estimated time is shown before you start each survey.'
      },
      {
        q: 'Can I take surveys on my mobile phone?',
        a: 'Yes! Our platform is fully mobile-responsive. You can take surveys on any device - phone, tablet, or computer.'
      },
    ]
  },
  {
    category: 'Reward Points',
    questions: [
      {
        q: 'How do I earn points?',
        a: 'You earn points by completing surveys. Points are credited to your account immediately after successful completion. The point value varies based on survey length and complexity.'
      },
      {
        q: 'Do my points expire?',
        a: 'No, your points never expire as long as your account remains active. However, accounts inactive for more than 12 months may be subject to closure.'
      },
      {
        q: 'How many points do I need to redeem?',
        a: 'The minimum redemption threshold is ₹100 (100 points). Different reward options may have different minimum requirements.'
      },
      {
        q: 'When will I receive my reward?',
        a: 'Redemption requests are processed within 3-5 business days. Digital gift cards are sent via email, while UPI/PayPal transfers may take slightly longer.'
      },
    ]
  },
  {
    category: 'Redemption Options',
    questions: [
      {
        q: 'What rewards can I redeem?',
        a: 'We offer Amazon gift cards, Flipkart gift cards, PayPal transfers, UPI transfers, and charitable donations.'
      },
      {
        q: 'How do I receive my Amazon/Flipkart gift card?',
        a: 'Gift card codes are sent to your registered email address within 3-5 business days of redemption request.'
      },
      {
        q: 'Is there a fee for redemption?',
        a: 'No, there are no fees for redeeming your points. The full value is transferred to you.'
      },
      {
        q: 'Can I cancel a redemption request?',
        a: 'Redemption requests can be cancelled within 24 hours if not yet processed. Contact support for assistance.'
      },
    ]
  },
];

function AccordionItem({ question, answer, isOpen, onClick }) {
  return (
    <div className="border-b border-gray-100 last:border-b-0">
      <button
        className="w-full py-4 flex items-center justify-between text-left"
        onClick={onClick}
      >
        <span className="font-medium text-gray-800">{question}</span>
        <svg
          className={`w-5 h-5 text-gray-500 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {isOpen && (
        <div className="pb-4 text-gray-600 panel-animate-in">
          {answer}
        </div>
      )}
    </div>
  );
}

export default function FAQ() {
  const [openItems, setOpenItems] = useState({});

  const toggleItem = (categoryIndex, questionIndex) => {
    const key = `${categoryIndex}-${questionIndex}`;
    setOpenItems(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

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
          <h1 className="text-3xl font-bold">Frequently Asked Questions</h1>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        {faqData.map((category, catIndex) => (
          <div key={catIndex} className="mb-8">
            <h2 className="text-xl font-semibold text-gray-800 mb-4">{category.category}</h2>
            <div className="bg-white rounded-xl shadow-sm border border-gray-100 px-6">
              {category.questions.map((item, qIndex) => (
                <AccordionItem
                  key={qIndex}
                  question={item.q}
                  answer={item.a}
                  isOpen={openItems[`${catIndex}-${qIndex}`]}
                  onClick={() => toggleItem(catIndex, qIndex)}
                />
              ))}
            </div>
          </div>
        ))}

        {/* Contact Section */}
        <div className="mt-12 bg-panel-primary-50 rounded-xl p-8 text-center">
          <h3 className="text-xl font-semibold text-gray-800 mb-2">Still have questions?</h3>
          <p className="text-gray-600 mb-4">
            Our support team is here to help you.
          </p>
          <a
            href="mailto:support@surveyfieldwork.com"
            className="panel-btn-primary inline-flex"
          >
            Contact Support
          </a>
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
