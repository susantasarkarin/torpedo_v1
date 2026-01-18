/**
 * Panel Layout Component
 * Main layout wrapper for authenticated panel pages
 */

import { Outlet } from 'react-router-dom';
import PanelHeader from './PanelHeader';
import PanelFooter from './PanelFooter';
import '../../styles/panel.css';

export default function PanelLayout() {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      <PanelHeader />
      
      <main className="flex-1">
        <Outlet />
      </main>

      <PanelFooter />
    </div>
  );
}
