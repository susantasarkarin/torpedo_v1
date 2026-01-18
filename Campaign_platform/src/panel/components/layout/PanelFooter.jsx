/**
 * Panel Footer Component
 * Footer with links to Terms, Privacy, FAQ, and contact info
 */

import { Link } from 'react-router-dom';

export default function PanelFooter() {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="panel-footer">
      <div className="max-w-7xl mx-auto">
        {/* Links */}
        <nav className="mb-4">
          <Link to="/panel/terms">Terms & Conditions</Link>
          <Link to="/panel/privacy">Privacy Policy</Link>
          <Link to="/panel/faq">FAQ</Link>
          <Link to="/panel/why-join">Why Join?</Link>
        </nav>

        {/* Copyright */}
        <p className="text-white/50 text-sm">
          © {currentYear} Survey Fieldwork. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
