import React from 'react';
import {
  LogIn,
  BookOpen,
  FlaskConical,
  BrainCircuit,
  Activity,
  BarChart3,
  Share2,
  Code
} from 'lucide-react';
import BlurText from '../components/BlurText';
import SpotlightCard from '../components/SpotlightCard';

export default function LandingPage({ setCurrentView }) {
  return (
    <div style={{ minHeight: '100vh', color: '#fff', position: 'relative', zIndex: 1, paddingBottom: '60px' }}>
      {/* Top Navbar */}
      <header style={{
        height: '70px',
        padding: '0 40px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 16px rgba(99, 102, 241, 0.5)'
            }}>
              <span style={{ fontWeight: '800', fontSize: '14px', color: '#fff' }}>CD</span>
            </div>
            <span style={{ fontWeight: '700', fontSize: '18px', letterSpacing: '-0.5px' }}>CD-SET</span>
          </div>

          <nav style={{ display: 'flex', gap: '20px', fontSize: '13px', color: '#94a3b8' }}>
            <a href="#docs" className="nav-link" onClick={(e) => { e.preventDefault(); setCurrentView('overview'); }} style={{ color: '#94a3b8' }}>Docs</a>
            <a href="#support" className="nav-link" onClick={(e) => { e.preventDefault(); setCurrentView('settings'); }} style={{ color: '#94a3b8' }}>Support</a>
          </nav>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            className="btn-secondary"
            onClick={() => setCurrentView('login')}
          >
            <LogIn size={14} />
            Sign In
          </button>
          <button
            className="btn-danger"
            onClick={() => setCurrentView('chaos-lab')}
          >
            Deploy Experiment
          </button>
        </div>
      </header>

      {/* Hero Section */}
      <section style={{ maxWidth: '900px', margin: '80px auto 100px auto', textAlign: 'center', padding: '0 20px' }}>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 16px',
          borderRadius: '9999px',
          background: 'rgba(99, 102, 241, 0.12)',
          border: '1px solid rgba(99, 102, 241, 0.3)',
          color: '#818cf8',
          fontSize: '11px',
          fontWeight: '700',
          letterSpacing: '1px',
          textTransform: 'uppercase',
          marginBottom: '24px'
        }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#818cf8', boxShadow: '0 0 8px #818cf8' }}></span>
          UPLOAD YOUR OWN PROJECT — GET A REAL RESILIENCE VERDICT
        </div>

        <div style={{ marginBottom: '24px' }}>
          <BlurText
            as="h1"
            text="Find out how your code actually fails."
            animateBy="letters"
            delay={20}
            style={{
              fontSize: '56px',
              fontWeight: '800',
              lineHeight: '1.1',
              letterSpacing: '-1.5px',
              textAlign: 'center',
              color: '#ffffff',
              margin: 0
            }}
          />
        </div>

        <div style={{ maxWidth: '680px', margin: '0 auto 36px auto' }}>
          <p style={{
            fontSize: '18px',
            color: '#94a3b8',
            lineHeight: '1.6',
            textAlign: 'center',
            margin: 0
          }}>Upload a project. CD-SET runs it in an isolated sandbox, injects real faults — malformed input, killed processes, dropped connections — and shows you exactly what broke, with the evidence to prove it. Then a tutor walks you through why.</p>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', gap: '16px' }}>
          <button
            className="btn-primary"
            style={{ padding: '12px 24px', fontSize: '15px' }}
            onClick={() => setCurrentView('login')}
          >
            <LogIn size={16} />
            Sign In
          </button>
          <button
            className="btn-secondary"
            style={{ padding: '12px 24px', fontSize: '15px' }}
            onClick={() => setCurrentView('overview')}
          >
            <BookOpen size={16} />
            Explore Docs
          </button>
        </div>
      </section>

      {/* Core Capabilities */}
      <section style={{ maxWidth: '1100px', margin: '0 auto 120px auto', padding: '0 20px' }}>
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <BlurText
            as="h2"
            text="Core Capabilities"
            animateBy="letters"
            delay={20}
            style={{ fontSize: '32px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '12px', textAlign: 'center' }}
          />
          <p style={{ color: '#94a3b8', fontSize: '15px', margin: 0 }}>Everything you need to break your system, understand why it broke, and fix it automatically.</p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '24px' }}>
          {/* Card 1 */}
          <SpotlightCard spotlightColor="rgba(239, 68, 68, 0.25)" style={{ padding: '28px', position: 'relative' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
              <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FlaskConical size={20} color="#ef4444" />
              </div>
              <span className="badge badge-degraded" style={{ fontSize: '10px' }}>● Sandboxed</span>
            </div>
            <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '8px' }}>Real fault injection</h3>
            <p style={{ color: '#94a3b8', fontSize: '13px', lineHeight: '1.6' }}>
              Your project runs as an actual process in an isolated sandbox copy — never the original. We send it malformed input, kill it mid-request, cut its network access, and record exactly what happens.
            </p>
          </SpotlightCard>

          {/* Card 2 */}
          <SpotlightCard spotlightColor="rgba(167, 139, 250, 0.25)" style={{ padding: '28px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(139, 92, 246, 0.15)', border: '1px solid rgba(139, 92, 246, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '20px' }}>
              <BrainCircuit size={20} color="#a78bfa" />
            </div>
            <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '8px' }}>AI Tutor</h3>
            <p style={{ color: '#94a3b8', fontSize: '13px', lineHeight: '1.6' }}>
              Every failure gets an 8-part explanation grounded in what your code actually did — the exception, the exit code, the fix — plus a comprehension question so the lesson sticks.
            </p>
          </SpotlightCard>

          {/* Card 3 */}
          <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.25)" style={{ padding: '28px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(245, 158, 11, 0.15)', border: '1px solid rgba(245, 158, 11, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '20px' }}>
              <Activity size={20} color="#f59e0b" />
            </div>
            <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '8px' }}>Live experiment logs</h3>
            <p style={{ color: '#94a3b8', fontSize: '13px', lineHeight: '1.6' }}>
              Watch each experiment run in real time — baseline request, fault injected, service checked again — with the raw evidence kept for you to inspect afterward.
            </p>
          </SpotlightCard>

          {/* Card 4 */}
          <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.25)" style={{ padding: '28px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '20px' }}>
              <BarChart3 size={20} color="#10b981" />
            </div>
            <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '8px' }}>Honest resilience scoring</h3>
            <p style={{ color: '#94a3b8', fontSize: '13px', lineHeight: '1.6' }}>
              A scorecard of what you actually tested and how much of it your code handled cleanly — clearly scoped to the scenarios run, not sold as a production guarantee.
            </p>
          </SpotlightCard>
        </div>
      </section>

      {/* How CD-SET Works */}
      <section style={{ maxWidth: '1100px', margin: '0 auto 100px auto', padding: '0 20px', borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: '80px' }}>
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <BlurText
            as="h2"
            text="How it works"
            animateBy="letters"
            delay={20}
            style={{ fontSize: '32px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '12px', textAlign: 'center' }}
          />
          <p style={{ color: '#94a3b8', fontSize: '15px', margin: 0 }}>From a project zip to a resilience verdict, in three steps.</p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '24px' }}>
          {/* Step 1 */}
          <SpotlightCard
            spotlightColor="rgba(99, 102, 241, 0.25)"
            style={{
              padding: '28px 20px',
              textAlign: 'center',
              borderRadius: '12px',
              background: 'linear-gradient(180deg, rgba(99, 102, 241, 0.08) 0%, rgba(15, 19, 32, 0.85) 45%)',
              border: '1px solid rgba(99, 102, 241, 0.22)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              minHeight: '260px'
            }}
          >
            <div>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(99, 102, 241, 0.15)',
                border: '1px solid rgba(99, 102, 241, 0.4)',
                color: '#818cf8',
                fontWeight: '700',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px auto',
                boxShadow: '0 0 16px rgba(99, 102, 241, 0.25)'
              }}>1</div>
              <h4 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '8px', textAlign: 'center' }}>Upload your project</h4>
              <p style={{ color: '#94a3b8', fontSize: '12px', lineHeight: '1.5', marginBottom: '16px' }}>
                Zip it up and upload it. CD-SET analyzes the code, detects the language and framework, and discovers where it can plausibly fail.
              </p>
            </div>
            <div style={{ background: '#0a0d16', padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(99, 102, 241, 0.2)', textAlign: 'left', fontFamily: 'monospace', fontSize: '11px', color: '#cbd5e1' }}>
              <div><span style={{ color: '#818cf8' }}>framework:</span> Flask</div>
              <div><span style={{ color: '#818cf8' }}>entrypoint:</span> app.py</div>
              <div><span style={{ color: '#818cf8' }}>status:</span> supported</div>
            </div>
          </SpotlightCard>

          {/* Step 2 */}
          <SpotlightCard
            spotlightColor="rgba(239, 68, 68, 0.25)"
            style={{
              padding: '28px 20px',
              textAlign: 'center',
              borderRadius: '12px',
              background: 'linear-gradient(180deg, rgba(239, 68, 68, 0.08) 0%, rgba(15, 19, 32, 0.85) 45%)',
              border: '1px solid rgba(239, 68, 68, 0.22)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              minHeight: '260px'
            }}
          >
            <div>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                color: '#f87171',
                fontWeight: '700',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px auto',
                boxShadow: '0 0 16px rgba(239, 68, 68, 0.25)'
              }}>2</div>
              <h4 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '8px', textAlign: 'center' }}>Run real experiments</h4>
              <p style={{ color: '#94a3b8', fontSize: '12px', lineHeight: '1.5', marginBottom: '16px' }}>
                Pick from generated experiments — malformed requests, killed processes, dropped connections — and run them against your code in an isolated sandbox copy.
              </p>
            </div>
            <div style={{ background: '#0a0d16', padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.2)', textAlign: 'left', fontFamily: 'monospace', fontSize: '11px', color: '#cbd5e1' }}>
              <div><span style={{ color: '#f87171' }}>fault:</span> HTTP 500 Spike</div>
              <div><span style={{ color: '#f87171' }}>target:</span> isolated-sandbox</div>
              <div><span style={{ color: '#f87171' }}>status:</span> injecting</div>
            </div>
          </SpotlightCard>

          {/* Step 3 */}
          <SpotlightCard
            spotlightColor="rgba(16, 185, 129, 0.25)"
            style={{
              padding: '28px 20px',
              textAlign: 'center',
              borderRadius: '12px',
              background: 'linear-gradient(180deg, rgba(16, 185, 129, 0.08) 0%, rgba(15, 19, 32, 0.85) 45%)',
              border: '1px solid rgba(16, 185, 129, 0.22)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              minHeight: '260px'
            }}
          >
            <div>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(16, 185, 129, 0.15)',
                border: '1px solid rgba(16, 185, 129, 0.4)',
                color: '#34d399',
                fontWeight: '700',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px auto',
                boxShadow: '0 0 16px rgba(16, 185, 129, 0.25)'
              }}>3</div>
              <h4 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '8px', textAlign: 'center' }}>Get the verdict, explained</h4>
              <p style={{ color: '#94a3b8', fontSize: '12px', lineHeight: '1.5', marginBottom: '16px' }}>
                See exactly what happened, backed by evidence, and read the Tutor's explanation of why — plus a question to check you actually understood it.
              </p>
            </div>
            <div style={{ background: '#0a0d16', padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.2)', textAlign: 'left', fontFamily: 'monospace', fontSize: '11px', color: '#cbd5e1' }}>
              <div><span style={{ color: '#34d399' }}>verdict:</span> RECOVERED</div>
              <div><span style={{ color: '#34d399' }}>score:</span> 94% resilience</div>
              <div><span style={{ color: '#34d399' }}>tutor:</span> RCA + fix ready</div>
            </div>
          </SpotlightCard>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid rgba(255, 255, 255, 0.06)', padding: '24px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#64748b', fontSize: '12px' }}>
        <div style={{ fontWeight: '700', color: '#94a3b8' }}>CD-SET</div>
        <div>© {new Date().getFullYear()} CD-SET. Built as a final-year diploma project.</div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <Share2 size={16} />
          <Code size={16} />
        </div>
      </footer>
    </div>
  );
}
