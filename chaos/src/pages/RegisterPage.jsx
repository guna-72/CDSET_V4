import React, { useState } from 'react';
import { ArrowLeft, UserPlus, User, Mail, Lock, ArrowRight, AlertCircle } from 'lucide-react';
import BlurText from '../components/BlurText';
import { useAuth } from '../context/AuthContext';
import { getAuthErrorMessage } from '../firebase';

export default function RegisterPage({ setCurrentView, redirectAfterLogin, setRedirectAfterLogin }) {
  const { register } = useAuth();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const targetDestination = redirectAfterLogin || (() => {
    try { return sessionStorage.getItem('redirectAfterLogin'); } catch { return null; }
  })();

  const getDestinationLabel = (target) => {
    switch (target) {
      case 'overview': return 'Documentation & Architecture';
      case 'settings': return 'Developer Support & Settings';
      case 'chaos-lab': return 'Chaos Lab & Experiment Deployment';
      default: return null;
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!name.trim()) {
      setError('Please enter your full name.');
      return;
    }

    if (!email.trim()) {
      setError('Please enter your email address.');
      return;
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters long.');
      return;
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      await register(name.trim(), email.trim(), password);
      let destination = redirectAfterLogin;
      if (!destination) {
        try { destination = sessionStorage.getItem('redirectAfterLogin'); } catch {}
      }
      destination = destination || 'dashboard';

      try { sessionStorage.removeItem('redirectAfterLogin'); } catch {}
      if (setRedirectAfterLogin) setRedirectAfterLogin(null);
      setCurrentView(destination);
    } catch (err) {
      setError(getAuthErrorMessage(err.code));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      width: '100%',
      position: 'relative',
      zIndex: 1,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '40px 20px'
    }}>
      {/* Plus-pattern grid canvas overlay */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundImage: `radial-gradient(rgba(255, 255, 255, 0.1) 1px, transparent 1px)`,
        backgroundSize: '24px 24px',
        opacity: 0.4,
        pointerEvents: 'none'
      }} />

      {/* Back to Home Button */}
      <button 
        className="btn-secondary"
        onClick={() => {
          try { sessionStorage.removeItem('redirectAfterLogin'); } catch {}
          if (setRedirectAfterLogin) setRedirectAfterLogin(null);
          setCurrentView('landing');
        }}
        style={{
          position: 'absolute',
          top: '30px',
          left: '30px',
          zIndex: 10
        }}
      >
        <ArrowLeft size={16} />
        Back to Home
      </button>

      {/* Centered Register Card */}
      <div className="glass-card glass-card-glow" style={{
        width: '100%',
        maxWidth: '440px',
        padding: '40px 32px',
        position: 'relative',
        zIndex: 2,
        borderRadius: '16px',
        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6)'
      }}>
        {/* Icon */}
        <div style={{
          width: '48px',
          height: '48px',
          borderRadius: '12px',
          background: 'rgba(99, 102, 241, 0.15)',
          border: '1px solid rgba(99, 102, 241, 0.3)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 20px auto'
        }}>
          <UserPlus size={22} color="#818cf8" />
        </div>

        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: '6px' }}>
          <BlurText as="h2" text="CD-SET" animateBy="letters" delay={20} style={{ fontSize: '24px', fontWeight: '700', color: '#fff', margin: 0, textAlign: 'center' }} />
        </div>
        <div style={{ textAlign: 'center', marginBottom: targetDestination && getDestinationLabel(targetDestination) ? '16px' : '24px' }}>
          <p style={{ fontSize: '13px', color: '#94a3b8', margin: 0 }}>Create your command center account</p>
        </div>

        {/* Destination Intent Notice */}
        {targetDestination && getDestinationLabel(targetDestination) && (
          <div style={{
            background: 'rgba(99, 102, 241, 0.12)',
            border: '1px solid rgba(99, 102, 241, 0.3)',
            borderRadius: '8px',
            padding: '10px 14px',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            color: '#c7d2fe',
            fontSize: '12px'
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#818cf8', flexShrink: 0 }} />
            <span>Create account to continue to <strong>{getDestinationLabel(targetDestination)}</strong></span>
          </div>
        )}

        {/* Error Alert */}
        {error && (
          <div style={{
            background: 'rgba(239, 68, 68, 0.12)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '8px',
            padding: '10px 14px',
            marginBottom: '18px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            color: '#fca5a5',
            fontSize: '12px'
          }}>
            <AlertCircle size={16} color="#ef4444" style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <label style={{ fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', color: '#94a3b8', display: 'block', marginBottom: '8px' }}>
              FULL NAME
            </label>
            <div style={{ position: 'relative' }}>
              <User size={16} color="#64748b" style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)' }} />
              <input 
                type="text" 
                placeholder="e.g. Alex Mercer"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                style={{
                  width: '100%',
                  background: 'rgba(11, 14, 22, 0.8)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '8px',
                  padding: '12px 14px 12px 40px',
                  color: '#fff',
                  fontSize: '13px',
                  outline: 'none'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', color: '#94a3b8', display: 'block', marginBottom: '8px' }}>
              EMAIL ADDRESS
            </label>
            <div style={{ position: 'relative' }}>
              <Mail size={16} color="#64748b" style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)' }} />
              <input 
                type="email" 
                placeholder="operator@domain.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                style={{
                  width: '100%',
                  background: 'rgba(11, 14, 22, 0.8)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '8px',
                  padding: '12px 14px 12px 40px',
                  color: '#fff',
                  fontSize: '13px',
                  outline: 'none'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', color: '#94a3b8', display: 'block', marginBottom: '8px' }}>
              PASSWORD
            </label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} color="#64748b" style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)' }} />
              <input 
                type="password" 
                placeholder="Min 6 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                style={{
                  width: '100%',
                  background: 'rgba(11, 14, 22, 0.8)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '8px',
                  padding: '12px 14px 12px 40px',
                  color: '#fff',
                  fontSize: '13px',
                  outline: 'none'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', color: '#94a3b8', display: 'block', marginBottom: '8px' }}>
              CONFIRM PASSWORD
            </label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} color="#64748b" style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)' }} />
              <input 
                type="password" 
                placeholder="Re-enter password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                style={{
                  width: '100%',
                  background: 'rgba(11, 14, 22, 0.8)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '8px',
                  padding: '12px 14px 12px 40px',
                  color: '#fff',
                  fontSize: '13px',
                  outline: 'none'
                }}
              />
            </div>
          </div>

          <button 
            type="submit"
            disabled={loading}
            className="btn-primary"
            style={{
              width: '100%',
              justifyContent: 'center',
              marginTop: '8px',
              padding: '12px',
              fontSize: '14px',
              fontWeight: '600',
              opacity: loading ? 0.7 : 1,
              cursor: loading ? 'not-allowed' : 'pointer'
            }}
          >
            {loading ? 'Registering...' : 'Create Account'}
            <ArrowRight size={16} />
          </button>
        </form>

        <p style={{ fontSize: '12px', color: '#94a3b8', textAlign: 'center', marginTop: '24px' }}>
          Already have an account?{' '}
          <a 
            href="#login" 
            onClick={(e) => { e.preventDefault(); setCurrentView('login'); }} 
            style={{ color: '#818cf8', textDecoration: 'none', fontWeight: '500', cursor: 'pointer' }}
          >
            Log In
          </a>
        </p>
      </div>

      {/* System Status */}
      <div style={{
        marginTop: '32px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        fontSize: '11px',
        fontWeight: '600',
        color: '#10b981',
        textTransform: 'uppercase',
        letterSpacing: '1px'
      }}>
        <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 10px #10b981' }}></span>
        SYSTEM OPERATIONAL
      </div>
    </div>
  );
}
