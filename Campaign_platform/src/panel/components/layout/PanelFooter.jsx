/**
 * Panel Footer Component
 * Footer with links to Terms, Privacy, FAQ, and contact info
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import PrivacyModal from '../../components/PrivacyModal';

export default function PanelFooter() {
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const currentYear = new Date().getFullYear();

  return (
    <>
      <footer className="panel-footer">
      <div className="max-w-7xl mx-auto">
        {/* Links */}
        <nav className="mb-4">
          <Link to="/panel/terms">Terms & Conditions</Link>
          <button type="button" onClick={() => setPrivacyOpen(true)} className="panel-footer-link">
            Privacy Policy
          </button>
          <Link to="/panel/faq">FAQ</Link>
          <Link to="/panel/why-join">Why Join?</Link>
        </nav>

        {/* Copyright */}
        <p className="text-white/50 text-sm">
          © {currentYear} Cogentix Research. All rights reserved.
        </p>
      </div>
    </footer>
    <PrivacyModal open={privacyOpen} onClose={() => setPrivacyOpen(false)} />
  </>
  )
}
