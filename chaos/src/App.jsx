import React, { useState, useEffect } from 'react';
import Lightfall from './components/Lightfall';
import Sidebar from './components/Sidebar';
import Navbar from './components/Navbar';
import AppErrorBoundary from './components/AppErrorBoundary';


import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import DashboardPage from './pages/DashboardPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import ImportPage from './pages/ImportPage';
import OverviewPage from './pages/OverviewPage';
import IdePage from './pages/IdePage';
import ChaosLabPage from './pages/ChaosLabPage';
import ExperimentsPage from './pages/ExperimentsPage';
import LogsPage from './pages/LogsPage';
import TutorPage from './pages/TutorPage';
import ReportsPage from './pages/ReportsPage';
import ResiliencePage from './pages/ResiliencePage';
import SettingsPage from './pages/SettingsPage';
import { AuthProvider, useAuth } from './context/AuthContext';
import { firebaseConfigured } from './firebase';

const NO_SHELL_VIEWS = ['landing', 'login', 'register', 'forgot-password'];

// Lightfall config per view
const getLightfallConfig = (view) => {
  const configs = {
    landing: {
      colors: ['#4f46e5', '#6366f1', '#a855f7', '#ec4899'],
      backgroundColor: '#07090e',
      speed: 0.18, streakCount: 5, streakWidth: 1.5, streakLength: 1.3,
      glow: 1.2, density: 0.7, twinkle: 0.4, zoom: 2.8,
      backgroundGlow: 0.4, opacity: 0.9, mouseInteraction: true, mouseStrength: 0.6
    },
    login: {
      colors: ['#4f46e5', '#6366f1', '#818cf8'],
      backgroundColor: '#050812',
      speed: 0.4, streakCount: 4, streakWidth: 1.2, streakLength: 1.0,
      glow: 0.9, density: 0.5, twinkle: 0.3, zoom: 2.5,
      backgroundGlow: 0.3, opacity: 0.75, mouseInteraction: true, mouseStrength: 0.4
    },
    register: {
      colors: ['#4f46e5', '#6366f1', '#818cf8'],
      backgroundColor: '#050812',
      speed: 0.4, streakCount: 4, streakWidth: 1.2, streakLength: 1.0,
      glow: 0.9, density: 0.5, twinkle: 0.3, zoom: 2.5,
      backgroundGlow: 0.3, opacity: 0.75, mouseInteraction: true, mouseStrength: 0.4
    },
    'forgot-password': {
      colors: ['#4f46e5', '#6366f1', '#818cf8'],
      backgroundColor: '#050812',
      speed: 0.4, streakCount: 4, streakWidth: 1.2, streakLength: 1.0,
      glow: 0.9, density: 0.5, twinkle: 0.3, zoom: 2.5,
      backgroundGlow: 0.3, opacity: 0.75, mouseInteraction: true, mouseStrength: 0.4
    },
    default: {
      colors: ['#1e1b4b', '#312e81', '#4338ca', '#4f46e5'],
      backgroundColor: '#04060a',
      speed: 0.3, streakCount: 3, streakWidth: 1.0, streakLength: 1.1,
      glow: 0.8, density: 0.5, twinkle: 0.25, zoom: 2.6,
      backgroundGlow: 0.25, opacity: 0.55, mouseInteraction: true, mouseStrength: 0.3
    },
    'chaos-lab': {
      colors: ['#7f1d1d', '#991b1b', '#dc2626', '#ef4444', '#f97316'],
      backgroundColor: '#0a0404',
      speed: 0.6, streakCount: 5, streakWidth: 1.4, streakLength: 1.2,
      glow: 1.1, density: 0.65, twinkle: 0.5, zoom: 2.7,
      backgroundGlow: 0.35, opacity: 0.65, mouseInteraction: true, mouseStrength: 0.5
    },
    logs: {
      colors: ['#064e3b', '#065f46', '#10b981', '#34d399'],
      backgroundColor: '#020a06',
      speed: 0.35, streakCount: 4, streakWidth: 1.1, streakLength: 1.2,
      glow: 0.9, density: 0.55, twinkle: 0.3, zoom: 2.5,
      backgroundGlow: 0.28, opacity: 0.5, mouseInteraction: false, mouseStrength: 0
    },
    tutor: {
      colors: ['#1e1b4b', '#4338ca', '#6366f1', '#818cf8', '#a5b4fc'],
      backgroundColor: '#050812',
      speed: 0.3, streakCount: 3, streakWidth: 1.0, streakLength: 1.3,
      glow: 0.85, density: 0.5, twinkle: 0.2, zoom: 2.4,
      backgroundGlow: 0.3, opacity: 0.5, mouseInteraction: true, mouseStrength: 0.25
    }
  };
  return configs[view] || configs.default;
};

function AppShell() {
  const { currentUser, loading } = useAuth();
  // Always start on the landing page for a fresh app launch, regardless of
  // whatever view was last open. (Previously this restored the last view
  // from localStorage, which is why the app could reopen on the dashboard.)
  const [currentView, setCurrentView] = useState('landing');
  const [selectedProjectId, setSelectedProjectId] = useState(() => localStorage.getItem('chaosTutorProjectId') || '');

  const isShell = !NO_SHELL_VIEWS.includes(currentView);
  const lfConfig = getLightfallConfig(currentView);

  // Remember where the user was so a page refresh doesn't dump them back
  // to the landing page. Auth/landing views are intentionally excluded —
  // those should always start fresh.
  const goToView = (view) => {
    setCurrentView(view);
    if (NO_SHELL_VIEWS.includes(view)) {
      localStorage.removeItem('chaosTutorView');
    } else {
      localStorage.setItem('chaosTutorView', view);
    }
  };

  // Route guard for protected views. Only meaningful when Firebase auth is
  // actually configured — the backend's token-less "local" single-user mode
  // has no notion of a signed-in user, so there's nothing to guard there.
  // When Firebase IS configured, a protected view reached with no signed-in
  // user (most commonly: `chaosTutorView` restored from localStorage on a
  // logged-out visit) is bounced back to the landing page once auth state
  // has settled, instead of rendering app chrome for a visitor who was
  // never authenticated.
  useEffect(() => {
    if (!firebaseConfigured || loading) return;
    if (!currentUser && isShell) {
      goToView('landing');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firebaseConfigured, loading, currentUser, isShell]);

  const renderPage = () => {
    const props = { setCurrentView: goToView, selectedProjectId, setSelectedProjectId };
    switch (currentView) {
      case 'landing':         return <LandingPage {...props} />;
      case 'login':           return <LoginPage {...props} />;
      case 'register':        return <RegisterPage {...props} />;
      case 'forgot-password': return <ForgotPasswordPage {...props} />;
      case 'dashboard':       return <DashboardPage {...props} />;
      case 'projects':        return <ProjectDetailPage {...props} />;
      case 'import':          return <ImportPage {...props} />;
      case 'overview':        return <OverviewPage {...props} />;
      case 'ide':             return <IdePage {...props} />;
      case 'chaos-lab':       return <ChaosLabPage {...props} />;
      case 'experiments':     return <ExperimentsPage {...props} />;
      case 'logs':            return <LogsPage {...props} />;
      case 'tutor':           return <TutorPage {...props} />;
      case 'reports':         return <ReportsPage {...props} />;
      case 'resilience':      return <ResiliencePage {...props} />;
      case 'settings':        return <SettingsPage {...props} />;
      default:                return <DashboardPage {...props} />;
    }
  };

  // While Firebase is still resolving auth state for a protected view
  // (e.g. one restored from localStorage), hold off on rendering the shell
  // so a logged-out visitor never sees a flash of app chrome before the
  // redirect above kicks in.
  if (firebaseConfigured && loading && isShell) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: '#07090e', color: '#a5b4fc', fontFamily: 'system-ui, sans-serif', fontSize: 14
      }}>
        Loading…
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#07090e', position: 'relative' }}>
    {/* Fixed Lightfall WebGL Background */}
    <div style={{
      position: 'fixed',
      top: 0, left: 0,
      width: '100vw',
      height: '100vh',
      zIndex: 0,
      pointerEvents: 'none'
    }}>
      <Lightfall {...lfConfig} />
    </div>

    {/* Dark overlay for readability */}
    <div style={{
      position: 'fixed',
      top: 0, left: 0,
      width: '100vw',
      height: '100vh',
      background: isShell
        ? 'rgba(7, 9, 14, 0.55)'
        : 'rgba(7, 9, 14, 0.40)',
      zIndex: 1,
      pointerEvents: 'none'
    }} />

    {/* App Shell */}
    {isShell ? (
      <div style={{ position: 'relative', zIndex: 2, display: 'flex', minHeight: '100vh' }}>
        <Sidebar
          currentView={currentView}
          setCurrentView={goToView}
        />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
          <Navbar setCurrentView={goToView} />
          <main style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
            {renderPage()}
          </main>
        </div>
      </div>
    ) : (
      <div key={currentView} style={{ position: 'relative', zIndex: 2 }}>
        {renderPage()}
      </div>
    )}
    </div>
  );
}

export default function App() {
  return (
    <AppErrorBoundary>
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </AppErrorBoundary>
  );
}
