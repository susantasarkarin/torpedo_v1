/**
 * Panel Header Component
 * Navigation header for the Survey Panel with logo, nav links, points display, and user menu
 */

import { useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { usePanelAuth } from '../../context/PanelAuthContext';

export default function PanelHeader() {
  const { panelist, logout } = usePanelAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/panel/login');
  };

  const navLinkClass = ({ isActive }) =>
    `text-sm font-medium tracking-wide transition-colors ${
      isActive ? 'text-white' : 'text-white/70 hover:text-white'
    }`;

  return (
    <header className="panel-header">
      {/* Logo */}
      <Link to="/panel/dashboard" className="flex items-center gap-2">
        <span className="text-2xl font-bold text-white">
          Sur<span className="text-panel-accent">v</span>ey
        </span>
        <span className="bg-panel-accent text-white text-xs font-bold px-2 py-0.5 rounded">
          FIELDWORK
        </span>
      </Link>

      {/* Navigation */}
      <nav className="panel-header-nav hidden md:flex">
        <NavLink to="/panel/dashboard" className={navLinkClass}>
          SURVEYS
        </NavLink>
        <NavLink to="/panel/rewards" className={navLinkClass}>
          REWARD
        </NavLink>
        <NavLink to="/panel/profile" className={navLinkClass}>
          PROFILE
        </NavLink>
      </nav>

      {/* User Section */}
      <div className="panel-header-user">
        {/* Points Badge */}
        <div className="panel-points-badge">
          <span>₹</span>
          <span>{panelist?.rewardsBalance?.toFixed(0) || '0'}</span>
          <span className="text-white/70 text-xs ml-1">Accumulated</span>
        </div>

        {/* Divider */}
        <span className="text-white/30">|</span>

        {/* User Dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-1 text-white text-sm hover:text-white/80 transition-colors"
          >
            <span>Hi {panelist?.firstName || 'User'}</span>
            <svg
              className={`w-4 h-4 transition-transform ${showUserMenu ? 'rotate-180' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {/* Dropdown Menu */}
          {showUserMenu && (
            <div className="absolute right-0 top-full mt-2 w-48 bg-white rounded-lg shadow-lg py-1 z-50">
              <Link
                to="/panel/profile"
                className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                onClick={() => setShowUserMenu(false)}
              >
                My Profile
              </Link>
              <Link
                to="/panel/rewards"
                className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                onClick={() => setShowUserMenu(false)}
              >
                My Rewards
              </Link>
              <hr className="my-1" />
              <button
                onClick={handleLogout}
                className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
              >
                Logout
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Mobile Menu Button */}
      <button className="md:hidden text-white">
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
    </header>
  );
}
