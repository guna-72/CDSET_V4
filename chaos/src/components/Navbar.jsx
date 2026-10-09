import React from 'react';
import { Search, Bell, User, Zap, LogOut } from 'lucide-react';
import Tooltip from './Tooltip';
import { useAuth } from '../context/AuthContext';

export default function Navbar({ setCurrentView, onDeployClick }) {
  const { currentUser, userProfile, logout } = useAuth();
  return (
    <header style={{
      height: '64px',
      padding: '0 24px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      background: 'rgba(11, 14, 22, 0.65)',
      backdropFilter: 'blur(16px)',
      borderBottom: '1px solid var(--border-color)',
      position: 'sticky',
      top: 0,
      zIndex: 15
    }}>
      {/* Search Input */}
      <Tooltip position="bottom" title="Search" text="Search your projects, experiments, and log entries">
        <div style={{ position: 'relative', width: '320px' }}>
          <Search size={16} color="#64748b" style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }} />
          <input 
            type="text" 
            placeholder="Search resources, symbols, commands..." 
            style={{
              width: '100%',
              background: 'rgba(255, 255, 255, 0.04)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '8px',
              padding: '8px 12px 8px 36px',
              color: '#f3f4f6',
              fontSize: '13px',
              outline: 'none',
              boxSizing: 'border-box'
            }}
          />
        </div>
      </Tooltip>

      {/* Right Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        <nav style={{ display: 'flex', gap: '16px', fontSize: '13px', color: '#94a3b8' }}>
          <Tooltip position="bottom" title="Architecture Docs" text="View API reference, resilience patterns, and SDK tutorials">
            <a href="#docs" className="nav-link" onClick={(e) => { e.preventDefault(); setCurrentView('overview'); }} style={{ color: '#94a3b8' }}>
              Docs
            </a>
          </Tooltip>

          <Tooltip position="bottom" title="Developer Support" text="Open knowledgebase, troubleshooting logs, and assistance">
            <a href="#support" className="nav-link" onClick={(e) => { e.preventDefault(); setCurrentView('settings'); }} style={{ color: '#94a3b8' }}>
              Support
            </a>
          </Tooltip>
        </nav>

        {currentUser ? (
          <Tooltip position="bottom" title="Sign Out" text={`Currently signed in as ${currentUser.email}. Click to sign out.`}>
            <button 
              onClick={async () => {
                await logout();
                setCurrentView('landing');
              }}
              className="nav-action-btn"
              style={{
                background: 'transparent',
                border: 'none',
                color: '#94a3b8',
                fontSize: '13px',
                cursor: 'pointer',
                fontWeight: '500',
                padding: '6px 12px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <LogOut size={14} />
              Sign Out
            </button>
          </Tooltip>
        ) : (
          <Tooltip position="bottom" title="User Sign In" text="Switch account, manage developer profile, or sign in">
            <button 
              onClick={() => setCurrentView('login')}
              className="nav-action-btn"
              style={{
                background: 'transparent',
                border: 'none',
                color: '#cbd5e1',
                fontSize: '13px',
                cursor: 'pointer',
                fontWeight: '500',
                padding: '6px 12px',
                borderRadius: '6px'
              }}
            >
              Sign In
            </button>
          </Tooltip>
        )}

        <Tooltip position="bottom" title="Deploy Chaos Experiment" text="Open Chaos Lab to immediately configure and inject fault scenarios">
          <button 
            className="btn-primary"
            onClick={() => onDeployClick ? onDeployClick() : setCurrentView('chaos-lab')}
          >
            <Zap size={14} />
            Deploy Experiment
          </button>
        </Tooltip>

        {/* Notifications */}
        <Tooltip position="bottom" title="Live Telemetry Alerts" text="Open Logs to see this project's real recorded experiment events">
          <div className="nav-icon-badge" style={{ position: 'relative', padding: '4px', cursor: 'pointer' }} onClick={() => setCurrentView('logs')}>
            <Bell size={18} color="#94a3b8" style={{ transition: 'color 0.2s ease' }} />
            <span style={{
              position: 'absolute',
              top: '2px',
              right: '2px',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: '#ef4444',
              boxShadow: '0 0 8px #ef4444'
            }} />
          </div>
        </Tooltip>

        {/* User Avatar */}
        <Tooltip 
          position="bottom" 
          title={userProfile?.displayName || currentUser?.displayName || 'Operator Profile'} 
          text={currentUser?.email ? `${currentUser.email} • Click to configure account and API keys` : 'Click to configure settings'}
        >
          <div 
            onClick={() => setCurrentView('settings')}
            className="nav-avatar-btn"
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '2px solid rgba(255, 255, 255, 0.1)',
              cursor: 'pointer'
            }}
          >
            <User size={16} color="#fff" />
          </div>
        </Tooltip>
      </div>
    </header>
  );
}
