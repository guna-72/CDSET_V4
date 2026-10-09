import React from 'react';
import { 
  LayoutDashboard, 
  Folder, 
  UploadCloud, 
  Eye, 
  Code2, 
  FlaskConical, 
  Microscope, 
  FileText, 
  BrainCircuit, 
  BarChart3, 
  ShieldCheck, 
  Settings, 
  Zap,
  User,
  Activity
} from 'lucide-react';
import Dock from './Dock';
import Tooltip from './Tooltip';
import { useAuth } from '../context/AuthContext';

export default function Sidebar({ currentView, setCurrentView }) {
  const { currentUser, userProfile } = useAuth();
  const coreItems = [
    {
      id: 'dashboard',
      icon: <LayoutDashboard size={18} />,
      label: 'Dashboard',
      description: 'Your imported projects, recent runs, and quick actions to import or test a project.',
      onClick: () => setCurrentView('dashboard'),
      className: currentView === 'dashboard' ? 'active' : ''
    },
    {
      id: 'chaos-lab',
      icon: <FlaskConical size={18} />,
      label: 'Chaos Lab',
      description: 'Run controlled resilience tests such as slow responses, invalid input, service stops, configuration faults, and file faults against an isolated project copy.',
      onClick: () => setCurrentView('chaos-lab'),
      className: currentView === 'chaos-lab' ? 'active' : ''
    },
    {
      id: 'ide',
      icon: <Code2 size={18} />,
      label: 'Cloud IDE',
      description: 'Browse the complete imported project tree, edit files, and run supported source files in the isolated terminal.',
      onClick: () => setCurrentView('ide'),
      className: currentView === 'ide' ? 'active' : ''
    },
    {
      id: 'experiments',
      icon: <Microscope size={18} />,
      label: 'Experiments',
      description: 'Understandable resilience checks with recorded evidence, observed outcomes, and test history.',
      onClick: () => setCurrentView('experiments'),
      className: currentView === 'experiments' ? 'active' : ''
    }
  ];

  const observabilityItems = [
    {
      id: 'logs',
      icon: <FileText size={18} />,
      label: 'System Logs',
      description: 'Real-time logs for a running project, plus the recorded logs from each experiment run.',
      onClick: () => setCurrentView('logs'),
      className: currentView === 'logs' ? 'active' : ''
    },
    {
      id: 'tutor',
      icon: <BrainCircuit size={18} />,
      label: 'AI Tutor',
      description: 'Root-cause explanations for each run, with follow-up Q&A about what failed and why.',
      onClick: () => setCurrentView('tutor'),
      className: currentView === 'tutor' ? 'active' : ''
    },
    {
      id: 'reports',
      icon: <BarChart3 size={18} />,
      label: 'Reports & Analytics',
      description: 'Outcome breakdown, most-affected targets, and recommended fixes — built from this project\'s real run history.',
      onClick: () => setCurrentView('reports'),
      className: currentView === 'reports' ? 'active' : ''
    },
    {
      id: 'resilience',
      icon: <ShieldCheck size={18} />,
      label: 'Resilience Scorecard',
      description: 'Automated evaluation of architecture robustness and recovery performance.',
      onClick: () => setCurrentView('resilience'),
      className: currentView === 'resilience' ? 'active' : ''
    }
  ];

  const managementItems = [
    {
      id: 'projects',
      icon: <Folder size={18} />,
      label: 'Projects',
      description: 'View, switch between, and delete the projects you\'ve imported for testing.',
      onClick: () => setCurrentView('projects'),
      className: currentView === 'projects' ? 'active' : ''
    },
    {
      id: 'import',
      icon: <UploadCloud size={18} />,
      label: 'Import Project',
      description: 'Import a ZIP, file, folder, or public Git repository to analyze and resilience-test it.',
      onClick: () => setCurrentView('import'),
      className: currentView === 'import' ? 'active' : ''
    },
    {
      id: 'overview',
      icon: <Eye size={18} />,
      label: 'Overview',
      description: 'Detected framework, entrypoint, HTTP endpoints, env vars, and files for the selected project.',
      onClick: () => setCurrentView('overview'),
      className: currentView === 'overview' ? 'active' : ''
    },
    {
      id: 'settings',
      icon: <Settings size={18} />,
      label: 'Settings',
      description: 'Configure Gemini & Groq API keys for AI-assisted diagnosis, and app preferences.',
      onClick: () => setCurrentView('settings'),
      className: currentView === 'settings' ? 'active' : ''
    }
  ];

  return (
    <aside style={{
      width: '320px',
      minWidth: '320px',
      height: '100vh',
      position: 'sticky',
      top: 0,
      background: 'rgba(11, 14, 22, 0.92)',
      backdropFilter: 'blur(20px)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      zIndex: 25,
      userSelect: 'none',
      boxSizing: 'border-box',
      overflow: 'visible'
    }}>
      {/* Brand Header */}
      <Tooltip 
        title="CD-SET Architecture" 
        text="Return to Landing Page & Public Documentation" 
        position="right"
        style={{ width: '100%' }}
      >
        <div 
          onClick={() => setCurrentView(currentUser ? 'dashboard' : 'landing')}
          className="sidebar-brand"
          style={{
            padding: '16px 18px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
            cursor: 'pointer',
            width: '100%',
            boxSizing: 'border-box',
            transition: 'background 0.2s ease'
          }}
        >
          <div className="brand-icon-box" style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 18px rgba(99, 102, 241, 0.5)',
            flexShrink: 0
          }}>
            <Activity size={20} color="#fff" />
          </div>
          <div style={{ overflow: 'hidden' }}>
            <h1 style={{ fontSize: '16px', fontWeight: '800', letterSpacing: '-0.4px', color: '#fff', margin: 0, lineHeight: 1.2 }}>
              CD-SET
            </h1>
            <p style={{ fontSize: '10px', color: '#818cf8', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0, marginTop: '2px' }}>
              Chaos Tutor
            </p>
          </div>
        </div>
      </Tooltip>

      {/* Navigation Groups with Dock Proximity and Names */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        overflowX: 'hidden',
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}>
        {/* Group 1: Core Platform */}
        <div>
          <div style={{
            fontSize: '10px',
            fontWeight: '700',
            color: '#64748b',
            letterSpacing: '0.6px',
            textTransform: 'uppercase',
            marginBottom: '6px',
            paddingLeft: '4px'
          }}>
            Core Platform
          </div>
          <Dock
            direction="vertical"
            showLabelOnRight={true}
            items={coreItems}
            baseItemSize={36}
            magnification={42}
            distance={70}
          />
        </div>

        {/* Group 2: Observability & AI */}
        <div>
          <div style={{
            fontSize: '10px',
            fontWeight: '700',
            color: '#64748b',
            letterSpacing: '0.6px',
            textTransform: 'uppercase',
            marginBottom: '6px',
            paddingLeft: '4px'
          }}>
            Observability & AI
          </div>
          <Dock
            direction="vertical"
            showLabelOnRight={true}
            items={observabilityItems}
            baseItemSize={36}
            magnification={42}
            distance={70}
          />
        </div>

        {/* Group 3: Management */}
        <div>
          <div style={{
            fontSize: '10px',
            fontWeight: '700',
            color: '#64748b',
            letterSpacing: '0.6px',
            textTransform: 'uppercase',
            marginBottom: '6px',
            paddingLeft: '4px'
          }}>
            Management
          </div>
          <Dock
            direction="vertical"
            showLabelOnRight={true}
            items={managementItems}
            baseItemSize={36}
            magnification={42}
            distance={70}
          />
        </div>
      </div>

      {/* Bottom Actions & User Profile */}
      <div style={{
        padding: '12px 14px',
        borderTop: '1px solid rgba(255, 255, 255, 0.05)',
        background: 'rgba(7, 9, 14, 0.5)',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px'
      }}>
        <Tooltip
          title="Chaos Lab"
          text="Go run a real fault-injection experiment against an imported project"
          position="right"
          style={{ width: '100%' }}
        >
          <button
            onClick={() => setCurrentView('chaos-lab')}
            className="btn-danger"
            style={{
              width: '100%',
              justifyContent: 'center',
              padding: '8px 12px',
              fontSize: '11px',
              fontWeight: '700',
              letterSpacing: '0.5px',
              textTransform: 'uppercase',
              gap: '6px'
            }}
          >
            <Zap size={14} />
            Run Chaos Experiment
          </button>
        </Tooltip>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', paddingTop: '4px' }}>
          <Tooltip 
            title={userProfile?.displayName || currentUser?.displayName || 'Operator Profile'} 
            text={currentUser?.email ? `Signed in as ${currentUser.email} • Click to open settings` : 'Click to configure settings'} 
            position="left"
          >
            <div 
              onClick={() => setCurrentView('settings')}
              className="sidebar-footer-item"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '5px 8px',
                borderRadius: '6px',
                color: '#94a3b8',
                fontSize: '11px',
                cursor: 'pointer',
                maxWidth: '120px',
                overflow: 'hidden'
              }}
            >
              <User size={14} style={{ flexShrink: 0 }} />
              <span style={{ 
                fontWeight: '600', 
                color: '#cbd5e1',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              }}>
                {userProfile?.displayName || currentUser?.displayName || (currentUser?.email ? currentUser.email.split('@')[0] : 'Admin')}
              </span>
            </div>
          </Tooltip>
        </div>
      </div>
    </aside>
  );
}
