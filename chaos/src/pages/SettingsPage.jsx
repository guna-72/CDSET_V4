import React, { useState, useEffect, useRef } from 'react';
import { 
  Eye, EyeOff, CheckCircle2, AlertCircle, Loader2, ShieldCheck, 
  User, Mail, Sparkles, Key, Check, RefreshCw, ExternalLink, 
  Shield, Server, Info, Terminal, Briefcase, Award, Camera, UploadCloud, Upload
} from 'lucide-react';
import { checkApiKey, getApiKeyStatus, getBackendSettingsKeys } from '../api';
import BlurText from '../components/BlurText';
import SpotlightCard from '../components/SpotlightCard';
import { useAuth } from '../context/AuthContext';
import { getStoredApiKeys, saveStoredApiKeys, SUPPORTED_PROVIDERS } from '../utils/apiKeys';
import { friendlyError } from '../utils/friendlyError';

const DEFAULT_AVATARS = [
  'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=150&auto=format&fit=crop&q=80',
];

const ROLES = [
  'Chaos Engineer',
  'SRE Lead',
  'Reliability Architect',
  'Full-Stack Developer',
  'Security Analyst',
  'DevOps Specialist',
  'Platform Administrator'
];

export default function SettingsPage({ setCurrentView }) {
  const { currentUser, userProfile, updateUserProfile } = useAuth();

  // ----------------------------------------------------
  // User Profile State
  // ----------------------------------------------------
  const [displayName, setDisplayName] = useState(
    userProfile?.displayName || currentUser?.displayName || 'System Administrator'
  );
  const [email, setEmail] = useState(
    userProfile?.email || currentUser?.email || 'operator@chaostutor.local'
  );
  const [role, setRole] = useState(
    userProfile?.role || 'Chaos Engineer'
  );
  const [avatarUrl, setAvatarUrl] = useState(
    userProfile?.avatarUrl || currentUser?.photoURL || DEFAULT_AVATARS[0]
  );
  const [bio, setBio] = useState(
    userProfile?.bio || 'Specializing in fault injection, distributed systems recovery, and automated resilience verification.'
  );
  const [department, setDepartment] = useState(
    userProfile?.department || 'Core Reliability & Infrastructure'
  );
  const [profileSaved, setProfileSaved] = useState(false);
  const fileInputRef = useRef(null);

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      alert('Please select a valid image file (PNG, JPG, WebP, GIF, etc.).');
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const img = new Image();
      img.onload = () => {
        // Optimize and resize image to max 256x256 to ensure quick storage and responsive UI
        const canvas = document.createElement('canvas');
        const maxDim = 256;
        let { width, height } = img;
        if (width > height) {
          if (width > maxDim) {
            height = Math.round((height * maxDim) / width);
            width = maxDim;
          }
        } else {
          if (height > maxDim) {
            width = Math.round((width * maxDim) / height);
            height = maxDim;
          }
        }
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.88);
        setAvatarUrl(dataUrl);
      };
      img.src = event.target.result;
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  // Sync profile when auth state updates
  useEffect(() => {
    if (userProfile) {
      if (userProfile.displayName) setDisplayName(userProfile.displayName);
      if (userProfile.email) setEmail(userProfile.email);
      if (userProfile.role) setRole(userProfile.role);
      if (userProfile.avatarUrl) setAvatarUrl(userProfile.avatarUrl);
      if (userProfile.bio) setBio(userProfile.bio);
      if (userProfile.department) setDepartment(userProfile.department);
    }
  }, [userProfile]);

  // ----------------------------------------------------
  // API Keys State
  // ----------------------------------------------------
  const [apiKeys, setApiKeys] = useState(() => {
    const stored = getStoredApiKeys();
    return {
      gemini: stored.gemini || '',
      groq: stored.groq || '',
      openai: stored.openai || '',
      anthropic: stored.anthropic || '',
      openrouter: stored.openrouter || '',
    };
  });

  const [showKeys, setShowKeys] = useState({
    gemini: false,
    groq: false,
    openai: false,
    anthropic: false,
    openrouter: false,
  });

  const [checkingKey, setCheckingKey] = useState({});
  const [keyChecks, setKeyChecks] = useState({});
  const [configuredKeys, setConfiguredKeys] = useState(null);
  const [checkingConfigured, setCheckingConfigured] = useState(false);
  const [backendSourceInfo, setBackendSourceInfo] = useState({});
  const [keysSaved, setKeysSaved] = useState(false);

  // Load backend key health status on mount
  useEffect(() => {
    let mounted = true;
    getBackendSettingsKeys()
      .then((res) => {
        if (mounted && res?.source_info) {
          setBackendSourceInfo(res.source_info);
        }
      })
      .catch(() => {});
    return () => { mounted = false; };
  }, []);

  const handleKeyChange = (provider, value) => {
    setApiKeys(prev => ({ ...prev, [provider]: value }));
    // Clear check status on edit
    if (keyChecks[provider]) {
      setKeyChecks(prev => {
        const next = { ...prev };
        delete next[provider];
        return next;
      });
    }
  };

  const toggleShowKey = (provider) => {
    setShowKeys(prev => ({ ...prev, [provider]: !prev[provider] }));
  };

  const handleTestKey = async (provider) => {
    const key = (apiKeys[provider] || '').trim();
    if (!key) {
      setKeyChecks(prev => ({
        ...prev,
        [provider]: { status: 'invalid', message: 'Enter a key first to test it.' }
      }));
      return;
    }

    setCheckingKey(prev => ({ ...prev, [provider]: true }));
    try {
      const res = await checkApiKey(provider, key);
      setKeyChecks(prev => ({ ...prev, [provider]: res }));
    } catch (e) {
      setKeyChecks(prev => ({
        ...prev,
        [provider]: { status: 'error', message: friendlyError(e) || 'Verification failed.' }
      }));
    } finally {
      setCheckingKey(prev => ({ ...prev, [provider]: false }));
    }
  };

  const handleCheckConfigured = async () => {
    setCheckingConfigured(true);
    try {
      const res = await getApiKeyStatus();
      setConfiguredKeys(res);
      if (res?.source_info) {
        setBackendSourceInfo(res.source_info);
      }
    } catch (e) {
      setConfiguredKeys({ error: friendlyError(e) || 'Could not query backend key status.' });
    } finally {
      setCheckingConfigured(false);
    }
  };

  const handleSaveProfile = async () => {
    const profileData = {
      displayName,
      email,
      role,
      avatarUrl,
      bio,
      department,
      updatedAt: new Date().toISOString()
    };
    if (updateUserProfile) {
      await updateUserProfile(profileData);
    } else {
      localStorage.setItem('chaosTutorSettings', JSON.stringify(profileData));
    }
    setProfileSaved(true);
    setTimeout(() => setProfileSaved(false), 2500);
  };

  const handleSaveApiKeys = async () => {
    await saveStoredApiKeys(apiKeys);
    setKeysSaved(true);
    // Refresh backend source status
    try {
      const res = await getBackendSettingsKeys();
      if (res?.source_info) setBackendSourceInfo(res.source_info);
    } catch {}
    setTimeout(() => setKeysSaved(false), 2500);
  };

  const handleSaveAll = async () => {
    await handleSaveProfile();
    await handleSaveApiKeys();
  };

  const statusStyle = (status) => ({
    working: ['#10b981', 'rgba(16,185,129,.12)', 'Working'],
    invalid: ['#ef4444', 'rgba(239,68,68,.12)', 'Invalid'],
    invalid_format: ['#f59e0b', 'rgba(245,158,11,.12)', 'Wrong format'],
    rate_limited: ['#f59e0b', 'rgba(245,158,11,.12)', 'Rate limited'],
    unreachable: ['#f59e0b', 'rgba(245,158,11,.12)', 'Unreachable'],
    provider_error: ['#f59e0b', 'rgba(245,158,11,.12)', 'Provider error'],
    format_only: ['#94a3b8', 'rgba(148,163,184,.12)', 'Format only'],
    error: ['#ef4444', 'rgba(239,68,68,.12)', 'Check failed'],
  }[status] || ['#94a3b8', 'rgba(148,163,184,.12)', status || 'Unknown']);

  const inputStyle = {
    width: '100%',
    background: 'rgba(11, 14, 22, 0.85)',
    border: '1px solid rgba(255, 255, 255, 0.12)',
    borderRadius: '8px',
    padding: '10px 14px',
    color: '#f3f4f6',
    fontSize: '13px',
    outline: 'none',
    fontFamily: 'inherit',
    transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
  };

  const labelStyle = {
    fontSize: '11px',
    fontWeight: '700',
    color: '#64748b',
    letterSpacing: '0.6px',
    textTransform: 'uppercase',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '8px'
  };

  return (
    <div style={{ padding: '32px', color: '#fff', zIndex: 1, position: 'relative', maxWidth: '1440px', margin: '0 auto' }}>
      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '32px', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <BlurText 
            as="h1" 
            text="Settings & Profile" 
            animateBy="letters" 
            delay={20} 
            style={{ fontSize: '28px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '6px' }} 
          />
          <p style={{ color: '#94a3b8', fontSize: '13px', margin: 0 }}>
            Configure your operator identity and manage LLM API keys. Keys set here take precedence over backend environment defaults.
          </p>
        </div>

        {/* Global Action Buttons */}
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            className="btn-secondary"
            onClick={() => setCurrentView('dashboard')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '9px 18px' }}
          >
            Back to Dashboard
          </button>
          <button
            className="btn-primary"
            onClick={handleSaveAll}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '9px 20px' }}
          >
            {profileSaved && keysSaved ? (
              <><Check size={16} /> All Saved!</>
            ) : (
              <><Sparkles size={16} /> Save All Changes</>
            )}
          </button>
        </div>
      </div>

      {/* Main 2-Column Layout: Left = User Profile, Right = API Keys */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '28px' }}>
        
        {/* ========================================================================= */}
        {/* LEFT COLUMN: USER PROFILE                                                 */}
        {/* ========================================================================= */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Profile Hero Card */}
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.25)" style={{ padding: '28px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '20px', marginBottom: '24px' }}>
              <div 
                style={{ position: 'relative', cursor: 'pointer' }}
                onClick={() => fileInputRef.current?.click()}
                title="Click to choose a photo from your computer"
              >
                <img
                  src={avatarUrl || DEFAULT_AVATARS[0]}
                  alt="Avatar"
                  onError={(e) => { e.target.src = DEFAULT_AVATARS[0]; }}
                  style={{
                    width: '78px',
                    height: '78px',
                    borderRadius: '50%',
                    objectFit: 'cover',
                    border: '3px solid #6366f1',
                    boxShadow: '0 0 20px rgba(99, 102, 241, 0.35)',
                    background: '#121520',
                    transition: 'opacity 0.2s ease'
                  }}
                />
                <div style={{
                  position: 'absolute',
                  bottom: '0',
                  right: '0',
                  width: '26px',
                  height: '26px',
                  borderRadius: '50%',
                  background: '#4f46e5',
                  border: '2px solid #0b0e16',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  boxShadow: '0 0 8px rgba(79,70,229,0.7)'
                }}>
                  <Camera size={13} />
                </div>
              </div>

              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                  <h2 style={{ fontSize: '20px', fontWeight: '700', color: '#f8fafc', margin: 0 }}>
                    {displayName || 'Operator Profile'}
                  </h2>
                  <span style={{
                    background: 'rgba(99, 102, 241, 0.15)',
                    border: '1px solid rgba(99, 102, 241, 0.4)',
                    color: '#a5b4fc',
                    fontSize: '11px',
                    fontWeight: '700',
                    padding: '2px 8px',
                    borderRadius: '12px'
                  }}>
                    {role}
                  </span>
                </div>
                <div style={{ color: '#94a3b8', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Mail size={13} style={{ color: '#6366f1' }} />
                  {email}
                </div>
                <div style={{ color: '#64748b', fontSize: '12px', marginTop: '4px' }}>
                  {department}
                </div>
              </div>
            </div>

            <div style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              borderRadius: '10px',
              padding: '14px 16px',
              marginBottom: '24px'
            }}>
              <div style={{ fontSize: '11px', fontWeight: '700', color: '#94a3b8', textTransform: 'uppercase', marginBottom: '4px' }}>
                Bio & Focus Area
              </div>
              <div style={{ fontSize: '13px', color: '#cbd5e1', lineHeight: '1.5' }}>
                {bio}
              </div>
            </div>

            {/* Quick Preset Avatar Selector & Computer Upload */}
            <div style={{ marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <label style={{ ...labelStyle, margin: 0 }}>
                  <Sparkles size={12} style={{ color: '#6366f1' }} /> AVATAR SELECTION
                </label>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  style={{
                    background: 'rgba(99, 102, 241, 0.15)',
                    border: '1px solid rgba(99, 102, 241, 0.45)',
                    color: '#c7d2fe',
                    borderRadius: '8px',
                    padding: '6px 14px',
                    fontSize: '11px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    boxShadow: '0 2px 8px rgba(99,102,241,0.2)',
                    transition: 'all 0.2s ease'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(99, 102, 241, 0.3)';
                    e.currentTarget.style.borderColor = '#818cf8';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(99, 102, 241, 0.15)';
                    e.currentTarget.style.borderColor = 'rgba(99, 102, 241, 0.45)';
                  }}
                >
                  <UploadCloud size={14} style={{ color: '#818cf8' }} /> Choose Photo from Computer
                </button>
              </div>

              {/* Hidden file input for uploading photo from computer */}
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept="image/*"
                style={{ display: 'none' }}
              />

              <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
                {DEFAULT_AVATARS.map((url, i) => (
                  <img
                    key={i}
                    src={url}
                    alt={`Preset ${i}`}
                    onClick={() => setAvatarUrl(url)}
                    title={`Select preset avatar ${i + 1}`}
                    style={{
                      width: '44px',
                      height: '44px',
                      borderRadius: '50%',
                      cursor: 'pointer',
                      border: avatarUrl === url ? '2.5px solid #6366f1' : '1px solid rgba(255,255,255,0.12)',
                      boxShadow: avatarUrl === url ? '0 0 14px rgba(99,102,241,0.6)' : 'none',
                      transition: 'all 0.2s ease',
                      opacity: avatarUrl === url ? 1 : 0.65
                    }}
                  />
                ))}

                {/* Circular Upload Tile Button */}
                <div
                  onClick={() => fileInputRef.current?.click()}
                  title="Upload custom photo from computer"
                  style={{
                    width: '44px',
                    height: '44px',
                    borderRadius: '50%',
                    cursor: 'pointer',
                    border: '1.5px dashed rgba(165, 180, 252, 0.5)',
                    background: 'rgba(99, 102, 241, 0.08)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#a5b4fc',
                    transition: 'all 0.2s ease'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#818cf8';
                    e.currentTarget.style.background = 'rgba(99, 102, 241, 0.22)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'rgba(165, 180, 252, 0.5)';
                    e.currentTarget.style.background = 'rgba(99, 102, 241, 0.08)';
                  }}
                >
                  <Camera size={18} />
                </div>

                {avatarUrl?.startsWith('data:image') && (
                  <span style={{
                    fontSize: '11px',
                    color: '#34d399',
                    background: 'rgba(16,185,129,0.12)',
                    border: '1px solid rgba(16,185,129,0.3)',
                    padding: '4px 10px',
                    borderRadius: '20px',
                    fontWeight: '600',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px'
                  }}>
                    <CheckCircle2 size={12} /> Custom Photo Loaded
                  </span>
                )}
              </div>
            </div>

            {/* Profile Form Fields */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div>
                  <label style={labelStyle}><User size={12} /> DISPLAY NAME</label>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="e.g. John Doe"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}><Briefcase size={12} /> ROLE ASSIGNMENT</label>
                  <select
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    style={{ ...inputStyle, cursor: 'pointer' }}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r} style={{ background: '#121520' }}>{r}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div>
                  <label style={labelStyle}><Mail size={12} /> EMAIL ADDRESS</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="operator@company.com"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}><Award size={12} /> DEPARTMENT / TEAM</label>
                  <input
                    type="text"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    placeholder="Platform Resilience"
                    style={inputStyle}
                  />
                </div>
              </div>

              <div>
                <label style={labelStyle}><Sparkles size={12} /> CUSTOM AVATAR URL</label>
                <input
                  type="text"
                  value={avatarUrl}
                  onChange={(e) => setAvatarUrl(e.target.value)}
                  placeholder="https://example.com/photo.png"
                  style={inputStyle}
                />
              </div>

              <div>
                <label style={labelStyle}>HEADLINE / OPERATOR BIO</label>
                <textarea
                  value={bio}
                  onChange={(e) => setBio(e.target.value)}
                  rows={3}
                  placeholder="Describe your engineering focus..."
                  style={{ ...inputStyle, resize: 'vertical' }}
                />
              </div>
            </div>

            {/* Profile Save Button */}
            <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'flex-end' }}>
              <button
                className="btn-primary"
                onClick={handleSaveProfile}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 24px' }}
              >
                {profileSaved ? (
                  <><Check size={16} /> Profile Saved!</>
                ) : (
                  <><CheckCircle2 size={16} /> Save Profile</>
                )}
              </button>
            </div>
          </SpotlightCard>

          {/* Account & Security Summary Card */}
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '22px 28px' }}>
            <h4 style={{ fontSize: '14px', fontWeight: '600', color: '#f3f4f6', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Shield size={16} style={{ color: '#10b981' }} /> Workspace Account Details
            </h4>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', fontSize: '12px' }}>
              <div style={{ background: 'rgba(255,255,255,0.03)', padding: '10px 12px', borderRadius: '8px' }}>
                <span style={{ color: '#64748b', display: 'block', marginBottom: '3px' }}>AUTH PROVIDER</span>
                <span style={{ color: '#e2e8f0', fontWeight: '600' }}>
                  {currentUser ? 'Firebase Authentication' : 'Local Offline Session'}
                </span>
              </div>
              <div style={{ background: 'rgba(255,255,255,0.03)', padding: '10px 12px', borderRadius: '8px' }}>
                <span style={{ color: '#64748b', display: 'block', marginBottom: '3px' }}>ACCOUNT UID</span>
                <span style={{ color: '#e2e8f0', fontFamily: 'monospace', fontSize: '11px' }}>
                  {currentUser?.uid ? `${currentUser.uid.slice(0, 16)}...` : 'local_operator'}
                </span>
              </div>
              <div style={{ background: 'rgba(255,255,255,0.03)', padding: '10px 12px', borderRadius: '8px' }}>
                <span style={{ color: '#64748b', display: 'block', marginBottom: '3px' }}>WORKSPACE STATUS</span>
                <span style={{ color: '#10b981', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981' }} /> Active & Verified
                </span>
              </div>
              <div style={{ background: 'rgba(255,255,255,0.03)', padding: '10px 12px', borderRadius: '8px' }}>
                <span style={{ color: '#64748b', display: 'block', marginBottom: '3px' }}>LOCAL STORAGE</span>
                <span style={{ color: '#a5b4fc', fontWeight: '600' }}>
                  Encrypted Browser Cache
                </span>
              </div>
            </div>
          </SpotlightCard>

        </div>

        {/* ========================================================================= */}
        {/* RIGHT COLUMN: API KEYS CONFIGURATION                                      */}
        {/* ========================================================================= */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.25)" style={{ padding: '28px' }}>
            
            {/* API Keys Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Key size={18} style={{ color: '#818cf8' }} />
                <h3 style={{ fontSize: '18px', fontWeight: '700', color: '#f3f4f6', margin: 0 }}>
                  LLM API Keys
                </h3>
              </div>
              <span style={{
                background: 'rgba(16,185,129,0.12)',
                border: '1px solid rgba(16,185,129,0.3)',
                color: '#10b981',
                padding: '3px 10px',
                borderRadius: '20px',
                fontSize: '11px',
                fontWeight: '700'
              }}>
                <ShieldCheck size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} /> Priority Enabled
              </span>
            </div>

            <p style={{ fontSize: '12.5px', color: '#94a3b8', lineHeight: '1.5', marginBottom: '18px' }}>
              Configure provider API keys for AI Tutor chat, automated fault diagnosis, and experiment generation.
            </p>

            {/* PRIORITY RULE BANNER */}
            <div style={{
              background: 'linear-gradient(135deg, rgba(99,102,241,0.12), rgba(168,85,247,0.08))',
              border: '1px solid rgba(99,102,241,0.3)',
              borderRadius: '10px',
              padding: '14px 16px',
              marginBottom: '24px',
              display: 'flex',
              gap: '12px',
              alignItems: 'flex-start'
            }}>
              <Info size={18} style={{ color: '#818cf8', flexShrink: 0, marginTop: '2px' }} />
              <div style={{ fontSize: '12px', lineHeight: '1.6', color: '#cbd5e1' }}>
                <strong style={{ color: '#c7d2fe', display: 'block', marginBottom: '2px' }}>
                  Execution Priority Rule:
                </strong>
                When running AI features, CD-SET <strong style={{ color: '#38bdf8' }}>first checks in Settings</strong> whether a key is configured. If a key is present, it uses that key. If a key is not set here, it automatically falls back to checking the keys in your backend <code style={{ background: 'rgba(0,0,0,0.4)', padding: '1px 5px', borderRadius: '4px', color: '#fbbf24' }}>.env</code> file.
              </div>
            </div>

            {/* Provider Key Inputs */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {SUPPORTED_PROVIDERS.map((provider) => {
                const keyVal = apiKeys[provider.id] || '';
                const isShown = showKeys[provider.id] || false;
                const isTesting = checkingKey[provider.id] || false;
                const checkRes = keyChecks[provider.id];
                const sourceInfo = backendSourceInfo[provider.id];

                // Determine active source badge
                let badgeText = 'Not Configured';
                let badgeColor = '#94a3b8';
                let badgeBg = 'rgba(148,163,184,0.1)';

                if (keyVal.trim()) {
                  badgeText = 'Settings Key (Active)';
                  badgeColor = '#34d399';
                  badgeBg = 'rgba(16,185,129,0.15)';
                } else if (sourceInfo?.active) {
                  badgeText = '.env Fallback (Active)';
                  badgeColor = '#38bdf8';
                  badgeBg = 'rgba(56,189,248,0.15)';
                }

                return (
                  <div 
                    key={provider.id}
                    style={{
                      background: 'rgba(255,255,255,0.02)',
                      border: '1px solid rgba(255,255,255,0.07)',
                      borderRadius: '10px',
                      padding: '16px',
                      transition: 'border-color 0.2s ease'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontSize: '13px', fontWeight: '700', color: '#f1f5f9' }}>
                            {provider.name}
                          </span>
                          <span style={{
                            fontSize: '10px',
                            fontWeight: '700',
                            padding: '2px 8px',
                            borderRadius: '10px',
                            background: badgeBg,
                            color: badgeColor,
                            border: `1px solid ${badgeColor}40`
                          }}>
                            {badgeText}
                          </span>
                        </div>
                        <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
                          {provider.desc}
                        </div>
                      </div>

                      <a 
                        href={provider.docs} 
                        target="_blank" 
                        rel="noreferrer" 
                        style={{ fontSize: '11px', color: '#818cf8', display: 'flex', alignItems: 'center', gap: '4px', textDecoration: 'none' }}
                      >
                        Get Key <ExternalLink size={11} />
                      </a>
                    </div>

                    {/* Input Field with Eye toggle and Test Key button */}
                    <div style={{ position: 'relative', marginTop: '10px' }}>
                      <input
                        type={isShown ? 'text' : 'password'}
                        value={keyVal}
                        onChange={(e) => handleKeyChange(provider.id, e.target.value)}
                        placeholder={provider.placeholder}
                        style={{
                          ...inputStyle,
                          paddingRight: '140px',
                          fontFamily: isShown ? 'monospace' : 'inherit'
                        }}
                        autoComplete="off"
                        spellCheck="false"
                      />

                      <div style={{ position: 'absolute', right: '6px', top: '5px', bottom: '5px', display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <button
                          type="button"
                          onClick={() => toggleShowKey(provider.id)}
                          title={isShown ? 'Hide key' : 'Show key'}
                          style={{
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: '6px',
                            color: '#94a3b8',
                            cursor: 'pointer',
                            padding: '4px 8px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            height: '28px'
                          }}
                        >
                          {isShown ? <EyeOff size={13} /> : <Eye size={13} />}
                        </button>

                        <button
                          type="button"
                          onClick={() => handleTestKey(provider.id)}
                          disabled={isTesting || !keyVal.trim()}
                          style={{
                            background: keyVal.trim() ? '#6366f1' : 'rgba(255,255,255,0.05)',
                            color: keyVal.trim() ? '#fff' : '#64748b',
                            border: 0,
                            borderRadius: '6px',
                            padding: '0 10px',
                            height: '28px',
                            fontSize: '11px',
                            fontWeight: '700',
                            cursor: keyVal.trim() && !isTesting ? 'pointer' : 'default',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px'
                          }}
                        >
                          {isTesting ? <Loader2 size={12} className="spin" /> : 'Test'}
                        </button>
                      </div>
                    </div>

                    {/* Test Key Result */}
                    {checkRes && (() => {
                      const [color, bg, label] = statusStyle(checkRes.status);
                      return (
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          padding: '8px 12px',
                          borderRadius: '6px',
                          background: bg,
                          border: `1px solid ${color}44`,
                          marginTop: '8px'
                        }}>
                          {checkRes.status === 'working' ? (
                            <CheckCircle2 size={14} color={color} />
                          ) : (
                            <AlertCircle size={14} color={color} />
                          )}
                          <div style={{ fontSize: '11px', flex: 1 }}>
                            <span style={{ color, fontWeight: '700', marginRight: '6px' }}>{label}:</span>
                            <span style={{ color: '#cbd5e1' }}>{checkRes.message}</span>
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                );
              })}
            </div>

            {/* Save Keys Action Button */}
            <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ color: '#64748b', fontSize: '11px' }}>
                Leaving a field blank will fall back to its backend <code style={{ color: '#94a3b8' }}>.env</code> setting.
              </div>

              <button
                className="btn-primary"
                onClick={handleSaveApiKeys}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 24px' }}
              >
                {keysSaved ? (
                  <><Check size={16} /> API Keys Saved!</>
                ) : (
                  <><Key size={16} /> Save API Keys</>
                )}
              </button>
            </div>
          </SpotlightCard>

          {/* Server .env Keys Inspector */}
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
              <div>
                <h4 style={{ fontSize: '14px', fontWeight: '600', color: '#f3f4f6', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Server size={15} style={{ color: '#38bdf8' }} /> Backend .env Keys Health
                </h4>
                <p style={{ color: '#64748b', fontSize: '11.5px', margin: '4px 0 0 0' }}>
                  Inspects keys loaded on the server machine without exposing the secrets.
                </p>
              </div>

              <button
                onClick={handleCheckConfigured}
                disabled={checkingConfigured}
                style={{
                  background: 'rgba(99,102,241,.12)',
                  border: '1px solid rgba(99,102,241,.4)',
                  color: '#a5b4fc',
                  borderRadius: '7px',
                  padding: '7px 12px',
                  cursor: 'pointer',
                  fontSize: '11px',
                  fontWeight: '700',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                {checkingConfigured ? <Loader2 size={12} className="spin" /> : <RefreshCw size={12} />}
                Check .env keys
              </button>
            </div>

            {configuredKeys?.error && (
              <div style={{ color: '#fca5a5', fontSize: '11px', marginTop: '10px', background: 'rgba(239,68,68,0.1)', padding: '8px', borderRadius: '6px' }}>
                {configuredKeys.error}
              </div>
            )}

            {configuredKeys?.keys?.length > 0 && (
              <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {configuredKeys.keys.map((item, i) => {
                  const [color, bg, label] = statusStyle(item.status);
                  return (
                    <div 
                      key={i} 
                      style={{ 
                        display: 'flex', 
                        alignItems: 'center', 
                        gap: '8px', 
                        padding: '8px 10px', 
                        background: bg, 
                        borderRadius: '6px',
                        border: `1px solid ${color}33`
                      }}
                    >
                      <span style={{ color: '#e2e8f0', fontSize: '11px', flex: 1, fontFamily: 'monospace' }}>
                        {item.provider.toUpperCase()} · key {item.index} · {item.key}
                      </span>
                      <span style={{ color, fontSize: '10px', fontWeight: '700' }}>
                        {label}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {configuredKeys && configuredKeys.keys?.length === 0 && (
              <div style={{ marginTop: '10px', color: '#64748b', fontSize: '11px' }}>
                No LLM provider keys were detected in the backend .env environment.
              </div>
            )}

            <div style={{ marginTop: '14px', padding: '9px 12px', borderRadius: '7px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.18)', color: '#94a3b8', fontSize: '10.5px', lineHeight: '1.5' }}>
              <strong style={{ color: '#fbbf24' }}>Note:</strong> Keys entered in the Settings panel above immediately override the .env keys for live tutoring and fault analysis without requiring a server restart.
            </div>
          </SpotlightCard>

        </div>

      </div>
    </div>
  );
}
