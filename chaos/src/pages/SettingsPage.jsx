import { friendlyError } from '../utils/friendlyError';
import React, { useState } from 'react';
import { Eye, EyeOff, CheckCircle2, AlertCircle, Loader2, ShieldCheck } from 'lucide-react';
import { checkApiKey, getApiKeyStatus } from '../api';
import BlurText from '../components/BlurText';
import SpotlightCard from '../components/SpotlightCard';


const SETTINGS_STORAGE_KEY = 'chaosTutorSettings';

const DEFAULT_SETTINGS = {
  displayName: 'System Administrator',
  role: 'Chaos Engineer',
  avatarUrl: 'https://example.com/avatar.png',
  fontSize: 14,
  keybindings: 'VS Code (Default)',
  theme: 'Obsidian',
  notifExperiment: true,
  notifCritical: false,
  notifTutor: false,
};

// Note: provider API keys are intentionally excluded from persistence here.
// They're handled by their own "Check key" / "Check configured keys" flow
// against the backend and are never something this page should write to
// localStorage in plain text.
function loadSavedSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function Toggle({ value, onChange }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={() => onChange(!value)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: '44px', height: '24px',
        borderRadius: '12px',
        background: value ? '#6366f1' : hovered ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.1)',
        position: 'relative',
        cursor: 'pointer',
        transition: 'all 0.2s ease',
        transform: hovered ? 'scale(1.06)' : 'scale(1)',
        border: value ? '1px solid rgba(99,102,241,0.7)' : hovered ? '1px solid rgba(255,255,255,0.25)' : '1px solid rgba(255,255,255,0.1)',
        boxShadow: value ? (hovered ? '0 0 16px rgba(99,102,241,0.6)' : '0 0 12px rgba(99,102,241,0.4)') : (hovered ? '0 0 10px rgba(255,255,255,0.1)' : 'none'),
        flexShrink: 0
      }}
    >
      <div style={{
        position: 'absolute',
        top: '3px',
        left: value ? '22px' : '3px',
        width: '16px', height: '16px',
        borderRadius: '50%',
        background: '#fff',
        transition: 'left 0.2s ease',
        boxShadow: '0 1px 4px rgba(0,0,0,0.4)'
      }} />
    </div>
  );
}

export default function SettingsPage({ setCurrentView }) {
  const [initialSettings] = useState(loadSavedSettings);
  const [displayName, setDisplayName] = useState(initialSettings.displayName);
  const [role, setRole] = useState(initialSettings.role);
  const [avatarUrl, setAvatarUrl] = useState(initialSettings.avatarUrl);
  const [geminiKey, setGeminiKey] = useState('••••••••••••••••••••••••••••••••');
  const [groqKey, setGroqKey] = useState('');
  const [showGemini, setShowGemini] = useState(false);
  const [showGroq, setShowGroq] = useState(false);
  const [keyProvider, setKeyProvider] = useState('auto');
  const [keyInput, setKeyInput] = useState('');
  const [customEndpoint, setCustomEndpoint] = useState('');
  const [keyCheck, setKeyCheck] = useState(null);
  const [checkingKey, setCheckingKey] = useState(false);
  const [configuredKeys, setConfiguredKeys] = useState(null);
  const [fontSize, setFontSize] = useState(initialSettings.fontSize);
  const [keybindings, setKeybindings] = useState(initialSettings.keybindings);
  const [theme, setTheme] = useState(initialSettings.theme);
  const [saved, setSaved] = useState(false);

  const [notifExperiment, setNotifExperiment] = useState(initialSettings.notifExperiment);
  const [notifCritical, setNotifCritical] = useState(initialSettings.notifCritical);
  const [notifTutor, setNotifTutor] = useState(initialSettings.notifTutor);

  const handleCheckKey = async () => {
    if (!keyInput.trim()) { setKeyCheck({ status: 'invalid', message: 'Enter an API key first.' }); return; }
    setCheckingKey(true); setKeyCheck(null);
    try { setKeyCheck(await checkApiKey(keyProvider, keyInput.trim(), customEndpoint.trim())); }
    catch (e) { setKeyCheck({ status: 'error', message: friendlyError(e) || 'Could not check the key.' }); }
    finally { setCheckingKey(false); }
  };

  const handleCheckConfigured = async () => {
    setCheckingKey(true);
    try { setConfiguredKeys(await getApiKeyStatus()); }
    catch (e) { setConfiguredKeys({ error: friendlyError(e) || 'Could not read backend key status.' }); }
    finally { setCheckingKey(false); }
  };

  const statusStyle = (status) => ({
    working: ['#10b981', 'rgba(16,185,129,.12)', 'Working'],
    invalid: ['#ef4444', 'rgba(239,68,68,.12)', 'Invalid'],
    invalid_format: ['#f59e0b', 'rgba(245,158,11,.12)', 'Wrong format'],
    rate_limited: ['#f59e0b', 'rgba(245,158,11,.12)', 'Rate limited'],
    unreachable: ['#f59e0b', 'rgba(245,158,11,.12)', 'Provider unreachable'],
    provider_error: ['#f59e0b', 'rgba(245,158,11,.12)', 'Provider error'],
    format_only: ['#94a3b8', 'rgba(148,163,184,.12)', 'Format only'],
    error: ['#ef4444', 'rgba(239,68,68,.12)', 'Check failed'],
  }[status] || ['#94a3b8', 'rgba(148,163,184,.12)', status || 'Unknown']);

  const handleSave = () => {
    try {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({
        displayName, role, avatarUrl, fontSize, keybindings, theme,
        notifExperiment, notifCritical, notifTutor,
      }));
    } catch {
      // localStorage can be unavailable (private browsing, quota, etc.) —
      // the in-session state is still updated, so the UI stays usable even
      // if the preference doesn't survive a refresh.
    }
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const inputStyle = {
    width: '100%',
    background: 'rgba(11, 14, 22, 0.8)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
    borderRadius: '8px',
    padding: '10px 14px',
    color: '#f3f4f6',
    fontSize: '13px',
    outline: 'none',
    fontFamily: 'inherit'
  };

  const labelStyle = {
    fontSize: '10px',
    fontWeight: '700',
    color: '#64748b',
    letterSpacing: '0.5px',
    textTransform: 'uppercase',
    display: 'block',
    marginBottom: '8px'
  };

  return (
    <div style={{ padding: '32px', color: '#fff', zIndex: 1, position: 'relative' }}>
      {/* Header */}
      <div style={{ marginBottom: '32px' }}>
        <BlurText as="h1" text="Workspace Settings" animateBy="letters" delay={20} style={{ fontSize: '28px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '4px' }} />
        <p style={{ color: '#94a3b8', fontSize: '13px', margin: 0 }}>Manage your CD-SET environment preferences and external integrations.</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
        {/* Left Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Profile & Identity */}
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '28px' }}>
            <h3 style={{ fontSize: '16px', fontWeight: '600', color: '#f3f4f6', marginBottom: '6px' }}>Profile & Identity</h3>
            <p style={{ fontSize: '12px', color: '#64748b', marginBottom: '24px' }}>Your display information within the CD-SET workspace.</p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
              <div>
                <label style={labelStyle}>DISPLAY NAME</label>
                <input
                  type="text"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  style={inputStyle}
                />
              </div>
              <div>
                <label style={labelStyle}>ROLE ASSIGNMENT</label>
                <select
                  value={role}
                  onChange={e => setRole(e.target.value)}
                  style={{ ...inputStyle, cursor: 'pointer' }}
                >
                  {['Chaos Engineer', 'SRE Lead', 'Developer', 'Security Analyst', 'Admin'].map(r => (
                    <option key={r} value={r} style={{ background: '#121520' }}>{r}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label style={labelStyle}>AVATAR URL</label>
              <div style={{ position: 'relative' }}>
                <div style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', width: '22px', height: '22px', borderRadius: '4px', background: 'rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>
                  🖼
                </div>
                <input
                  type="text"
                  value={avatarUrl}
                  onChange={e => setAvatarUrl(e.target.value)}
                  style={{ ...inputStyle, paddingLeft: '42px' }}
                />
              </div>
            </div>
          </SpotlightCard>

          {/* API Key Health */}
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '28px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: '600', color: '#f3f4f6' }}>API Key Health</h3>
              <span style={{ background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.3)', color: '#10b981', padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: '700' }}>
                <ShieldCheck size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} /> Secure check
              </span>
            </div>
            <p style={{ fontSize: '12px', color: '#64748b', marginBottom: '18px' }}>
              Check whether an API key is accepted by its provider. Keys entered here are checked temporarily and are never saved in the browser or returned by the server.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: '10px', marginBottom: '10px' }}>
              <select value={keyProvider} onChange={e => setKeyProvider(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
                {['auto','openai','groq','gemini','anthropic','deepseek','openrouter','mistral','cohere','together','xai','huggingface','custom'].map(p => <option key={p} value={p} style={{ background:'#121520' }}>{p === 'auto' ? 'Auto detect' : p === 'xai' ? 'xAI' : p === 'huggingface' ? 'Hugging Face' : p[0].toUpperCase()+p.slice(1)}</option>)}
              </select>
              <div style={{ position:'relative' }}>
                <input type="password" value={keyInput} onChange={e => setKeyInput(e.target.value)} placeholder="Paste API key to check" style={{ ...inputStyle, paddingRight: 120 }} autoComplete="off" spellCheck="false" />
                <button onClick={handleCheckKey} disabled={checkingKey} style={{ position:'absolute', right:6, top:5, bottom:5, border:0, borderRadius:6, padding:'0 14px', background:'#6366f1', color:'#fff', fontWeight:700, cursor:checkingKey?'wait':'pointer', opacity:checkingKey?.7:1 }}>
                  {checkingKey ? <Loader2 size={14} className="spin" /> : 'Check key'}
                </button>
              </div>
            </div>

            {keyProvider === 'custom' && (
              <input value={customEndpoint} onChange={e => setCustomEndpoint(e.target.value)} placeholder="Optional HTTPS verification endpoint (for custom/OpenAI-compatible keys)" style={{ ...inputStyle, marginBottom:10 }} />
            )}

            {keyCheck && (() => { const [color,bg,label] = statusStyle(keyCheck.status); return (
              <div style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 12px', borderRadius:8, background:bg, border:`1px solid ${color}55`, marginBottom:12 }}>
                {keyCheck.status === 'working' ? <CheckCircle2 size={16} color={color}/> : <AlertCircle size={16} color={color}/>}
                <div style={{ flex:1 }}><div style={{ color, fontSize:12, fontWeight:700 }}>{label}</div><div style={{ color:'#94a3b8', fontSize:11, marginTop:2 }}>{keyCheck.message}{keyCheck.provider ? ` · Provider: ${keyCheck.provider}` : ''}</div></div>
              </div>
            ); })()}

            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:4 }}>
              <div>
                <div style={{ color:'#e2e8f0', fontSize:12, fontWeight:600 }}>Server-configured keys</div>
                <div style={{ color:'#64748b', fontSize:11 }}>Checks keys from your backend environment without exposing them.</div>
              </div>
              <button onClick={handleCheckConfigured} disabled={checkingKey} style={{ background:'rgba(99,102,241,.12)', border:'1px solid rgba(99,102,241,.4)', color:'#a5b4fc', borderRadius:7, padding:'8px 12px', cursor:'pointer', fontSize:11, fontWeight:700 }}>Check configured keys</button>
            </div>

            {configuredKeys?.error && <div style={{ color:'#fca5a5', fontSize:11, marginTop:10 }}>{configuredKeys.error}</div>}
            {configuredKeys?.keys?.length > 0 && (
              <div style={{ marginTop:12, display:'flex', flexDirection:'column', gap:6 }}>
                {configuredKeys.keys.map((item, i) => { const [color,bg,label] = statusStyle(item.status); return <div key={i} style={{ display:'flex', alignItems:'center', gap:8, padding:'7px 9px', background:bg, borderRadius:6 }}><span style={{ color:'#e2e8f0', fontSize:11, flex:1 }}>{item.provider} · key {item.index} · {item.key}</span><span style={{ color, fontSize:10, fontWeight:700 }}>{label}</span></div>; })}
              </div>
            )}
            {configuredKeys?.keys?.length === 0 && <div style={{ marginTop:10, color:'#64748b', fontSize:11 }}>No provider keys are configured on the backend.</div>}

            <div style={{ marginTop:14, padding:'9px 11px', borderRadius:7, background:'rgba(245,158,11,.07)', border:'1px solid rgba(245,158,11,.18)', color:'#94a3b8', fontSize:10, lineHeight:1.5 }}>
              <strong style={{color:'#fbbf24'}}>Important:</strong> “Working” means the provider accepted the key during this check. It does not mean the key has unlimited quota or that every model is available. “Provider unreachable” is not the same as “invalid key.”
            </div>
          </SpotlightCard>
        </div>

        {/* Right Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* IDE Preferences */}
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#f3f4f6', marginBottom: '24px' }}>IDE Preferences</h3>

            {/* Font Size */}
            <div style={{ marginBottom: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <label style={labelStyle}>EDITOR FONT SIZE</label>
                <span style={{ fontSize: '12px', fontWeight: '700', color: '#818cf8' }}>{fontSize}px</span>
              </div>
              <div style={{ position: 'relative', padding: '6px 0' }}>
                <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', position: 'relative', overflow: 'hidden' }}>
                  <div style={{ width: `${((fontSize - 10) / 14) * 100}%`, height: '100%', background: '#6366f1', borderRadius: '2px' }} />
                </div>
                <input
                  type="range" min="10" max="24" value={fontSize}
                  onChange={e => setFontSize(Number(e.target.value))}
                  style={{ position: 'absolute', top: '2px', left: 0, width: '100%', opacity: 0, cursor: 'pointer', height: '16px' }}
                />
              </div>
            </div>

            {/* Keybindings */}
            <div style={{ marginBottom: '20px' }}>
              <label style={labelStyle}>KEYBINDINGS</label>
              <select
                value={keybindings}
                onChange={e => setKeybindings(e.target.value)}
                style={{ ...inputStyle, cursor: 'pointer' }}
              >
                {['VS Code (Default)', 'Vim', 'Emacs', 'Sublime Text'].map(k => (
                  <option key={k} value={k} style={{ background: '#121520' }}>{k}</option>
                ))}
              </select>
            </div>

            {/* Theme Override */}
            <div>
              <label style={labelStyle}>THEME OVERRIDE</label>
              <div style={{ display: 'flex', gap: '8px' }}>
                {['System', 'Obsidian'].map(t => (
                  <button
                    key={t}
                    onClick={() => setTheme(t)}
                    style={{
                      flex: 1,
                      background: theme === t ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.04)',
                      border: `1px solid ${theme === t ? '#6366f1' : 'rgba(255,255,255,0.1)'}`,
                      borderRadius: '8px',
                      padding: '10px',
                      color: theme === t ? '#818cf8' : '#94a3b8',
                      fontSize: '13px',
                      fontWeight: '600',
                      cursor: 'pointer'
                    }}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
          </SpotlightCard>

          {/* Alerts & Notifications */}
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#f3f4f6', marginBottom: '24px' }}>Alerts & Notifications</h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
              {[
                { label: 'Experiment Completion', desc: 'Notify when chaos injection ends.', value: notifExperiment, onChange: setNotifExperiment },
                { label: 'Critical Faults', desc: 'Alert on system degradation.', value: notifCritical, onChange: setNotifCritical },
                { label: 'Tutor Insights', desc: 'AI generated tips during runs.', value: notifTutor, onChange: setNotifTutor },
              ].map((n, idx) => (
                <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: '600', color: '#e2e8f0', marginBottom: '2px' }}>{n.label}</div>
                    <div style={{ fontSize: '11px', color: '#64748b' }}>{n.desc}</div>
                  </div>
                  <Toggle value={n.value} onChange={n.onChange} />
                </div>
              ))}
            </div>
          </SpotlightCard>

          {/* Save / Discard Buttons */}
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              className="btn-secondary"
              style={{ flex: 1, justifyContent: 'center' }}
              onClick={() => setCurrentView('dashboard')}
            >
              Discard
            </button>
            <button
              className="btn-primary"
              style={{ flex: 1, justifyContent: 'center' }}
              onClick={handleSave}
            >
              {saved ? <><CheckCircle2 size={15} /> Saved!</> : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
