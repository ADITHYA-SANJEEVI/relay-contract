import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { SyntheticBanner } from '../common/SyntheticBanner';

export const AppShell: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && sidebarOpen) {
        setSidebarOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [sidebarOpen]);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[var(--color-canvas)] text-[var(--color-text-primary)]">
      {/* Skip link for keyboard accessibility */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      {/* Persistent Synthetic Banner if in fixture mode */}
      <SyntheticBanner />

      <div className="flex flex-1 overflow-hidden">
        {/* Desktop Sidebar (Persistent at >= 1280px) */}
        <Sidebar className="hidden xl:flex" />

        {/* Mobile/Tablet Drawer Backdrop & Sidebar (< 1280px) */}
        {sidebarOpen && (
          <div 
            className="fixed inset-0 z-40 bg-black/60 xl:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />
        )}
        <div 
          className={`fixed inset-y-0 left-0 z-50 transform xl:hidden transition-transform duration-200 ease-in-out ${
            sidebarOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
          role="dialog"
          aria-label="Navigation drawer"
          aria-modal={sidebarOpen}
        >
          <Sidebar />
        </div>

        {/* Main Content Area */}
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
          <Header onToggleSidebar={() => setSidebarOpen(prev => !prev)} />
          <main 
            id="main-content" 
            className="flex-1 overflow-y-auto p-4 md:p-6" 
            tabIndex={-1}
            role="main"
          >
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
};
