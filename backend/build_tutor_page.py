import os

target_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chaos", "src", "pages", "TutorPage.jsx"))
v25_candidates = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chaos_tutor_final_submission_V25_NO_ANDROID", "chaos", "src", "pages", "TutorPage.jsx")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "chaos_tutor_final_submission_V25_NO_ANDROID", "chaos", "src", "pages", "TutorPage.jsx")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "chaos_tutor_final_submission_V25_FINAL_FIXED", "chaos", "src", "pages", "TutorPage.jsx")),
]
v25_file = next((p for p in v25_candidates if os.path.exists(p)), v25_candidates[0])

with open(v25_file, encoding="utf-8") as f:
    v25_code = f.read()

# Extract CSS exactly
style_start = v25_code.find("<style>{`") + 9
style_end = v25_code.find("`}</style>")
css = v25_code[style_start:style_end]

# Extra CSS for running spinner banner, top bar, auto-expanding textarea, and quick chips
extra_css = """
                .chaos-topBar {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 16px;
                    flex-wrap: wrap;
                    width: 100%;
                }

                .chaos-badge {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 5px 12px;
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: 700;
                }

                .chaos-actionBtn {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: rgba(99, 102, 241, 0.14);
                    border: 1px solid rgba(99, 102, 241, 0.35);
                    color: #c7d2fe;
                    padding: 6px 14px;
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    outline: none;
                }

                .chaos-actionBtn:hover {
                    background: rgba(99, 102, 241, 0.28);
                    border-color: rgba(99, 102, 241, 0.6);
                    color: #ffffff;
                }

                .chaos-runningBanner {
                    display: flex;
                    align-items: center;
                    gap: 14px;
                    background: linear-gradient(90deg, rgba(99, 102, 241, 0.16), rgba(79, 70, 229, 0.08));
                    border: 1px solid rgba(129, 140, 248, 0.35);
                    border-radius: 12px;
                    padding: 12px 18px;
                    margin-bottom: 18px;
                    box-shadow: 0 4px 20px -2px rgba(99, 102, 241, 0.2);
                    animation: chaosGlow 3s infinite ease-in-out;
                }

                @keyframes chaosGlow {
                    0%, 100% { border-color: rgba(129, 140, 248, 0.3); box-shadow: 0 4px 18px rgba(99, 102, 241, 0.15); }
                    50% { border-color: rgba(129, 140, 248, 0.6); box-shadow: 0 4px 24px rgba(99, 102, 241, 0.3); }
                }

                .chaos-runningSpinnerWrapper {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 36px;
                    height: 36px;
                    border-radius: 10px;
                    background: rgba(99, 102, 241, 0.18);
                    border: 1px solid rgba(129, 140, 248, 0.3);
                    flex-shrink: 0;
                }

                .chaos-runningContent {
                    flex: 1;
                    min-width: 0;
                }

                .chaos-runningHeadline {
                    font-size: 13px;
                    color: #f1f5f9;
                    font-weight: 600;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    flex-wrap: wrap;
                }

                .chaos-runningBadge {
                    font-size: 9px;
                    font-weight: 800;
                    letter-spacing: 0.6px;
                    background: rgba(129, 140, 248, 0.25);
                    color: #c7d2fe;
                    border: 1px solid rgba(129, 140, 248, 0.4);
                    border-radius: 4px;
                    padding: 2px 6px;
                    text-transform: uppercase;
                }

                .chaos-runningSub {
                    font-size: 12px;
                    color: #94a3b8;
                    margin-top: 2px;
                }

                .chaos-faultHighlight {
                    color: #fbbf24;
                    font-weight: 700;
                }

                .chaos-runningPill {
                    display: inline-flex;
                    align-items: center;
                    gap: 7px;
                    background: rgba(99, 102, 241, 0.18);
                    border: 1px solid rgba(129, 140, 248, 0.4);
                    color: #c7d2fe;
                    padding: 5px 12px;
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: 600;
                }

                .chaos-loadingNotice {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 14px;
                    background: rgba(99, 102, 241, 0.1);
                    border: 1px solid rgba(99, 102, 241, 0.25);
                    border-radius: 8px;
                    font-size: 12px;
                    color: #c7d2fe;
                    margin-bottom: 16px;
                }

                .chaos-activeTestAlert {
                    display: flex;
                    align-items: center;
                    gap: 9px;
                    background: rgba(99, 102, 241, 0.12);
                    border: 1px solid rgba(129, 140, 248, 0.25);
                    border-radius: 10px;
                    padding: 10px 14px;
                    margin-bottom: 16px;
                    font-size: 12px;
                    color: #c7d2fe;
                }

                .chaos-quickQuestions {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 6px;
                    padding: 4px 18px 8px 18px;
                    flex-shrink: 0;
                }

                .chaos-quickChip {
                    font-size: 11px;
                    color: #c7d2fe;
                    background: rgba(99, 102, 241, 0.12);
                    border: 1px solid rgba(99, 102, 241, 0.28);
                    border-radius: 999px;
                    padding: 4px 10px;
                    cursor: pointer;
                    transition: all 0.15s ease;
                    outline: none;
                    font-family: inherit;
                }

                .chaos-quickChip:hover:not(:disabled) {
                    background: rgba(99, 102, 241, 0.25);
                    border-color: rgba(99, 102, 241, 0.5);
                    color: #ffffff;
                }

                .chaos-quickChip:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }

                .chaos-chatInput {
                    position: relative;
                    margin: 8px 18px 18px 18px;
                    min-height: 52px;
                    height: auto;
                    border: 1px solid rgba(129, 140, 248, 0.22);
                    border-radius: 14px;
                    background: rgba(11, 14, 22, 0.94);
                    backdrop-filter: blur(12px);
                    display: flex;
                    align-items: flex-end;
                    padding: 8px 10px 8px 14px;
                    flex-shrink: 0;
                    z-index: 5;
                    gap: 8px;
                    transition: border-color 0.2s ease, box-shadow 0.2s ease;
                }

                .chaos-chatTextarea {
                    flex: 1;
                    min-width: 0;
                    min-height: 24px;
                    max-height: 140px;
                    background: transparent;
                    border: none;
                    outline: none;
                    color: #e2e8f0;
                    font-size: 13px;
                    line-height: 1.5;
                    font-family: inherit;
                    resize: none;
                    padding: 6px 0;
                    box-sizing: border-box;
                    overflow-y: auto;
                }

                .chaos-chatTextarea::placeholder {
                    color: #64748b;
                }

                .chaos-chatInput button {
                    width: 36px;
                    height: 36px;
                    border-radius: 10px;
                    background: linear-gradient(135deg, #6366f1, #4f46e5);
                    border: none;
                    color: #ffffff;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                    flex-shrink: 0;
                    margin-bottom: 2px;
                    transition: all 0.2s ease;
                    box-shadow: 0 2px 8px rgba(79, 70, 229, 0.3);
                }

                .chaos-chatInput button:hover:not(:disabled) {
                    background: linear-gradient(135deg, #4f46e5, #4338ca);
                    transform: translateY(-1px);
                    box-shadow: 0 4px 12px rgba(79, 70, 229, 0.45);
                }

                .chaos-chatInput button:disabled {
                    opacity: 0.45;
                    cursor: not-allowed;
                    transform: none;
                    box-shadow: none;
                }
"""

enhanced_css = css + "\n" + extra_css

part1 = """import React, { useState, useEffect, useRef } from 'react';
import {
    Sparkles, Send, Bot, UserRound, Loader2, Trash2, Copy, Check,
    ShieldCheck, Code2, AlertTriangle, Zap, RotateCcw, Folder
} from 'lucide-react';
import {
    getRunDiagnosis, getTutor, askTutor, getTutorContext,
    getProjectLatestRun, listRuns
} from '../api';

const getChatStorageKey = (runId, pId) => {
    if (runId) return `chaosTutorChat_run_${runId}`;
    if (pId) return `chaosTutorChat_proj_${pId}`;
    return 'chaosTutorChat_general';
};

const OUTCOME_LABEL = {
    PASSED: 'Handled correctly',
    RECOVERED: 'Recovered',
    APPLICATION_FAILURE: 'Application failed',
    CRASHED: 'Application crashed',
    WEAK_HANDLING: 'Accepted without validation',
    ANOMALY: 'Unexpected behavior',
    TARGET_UNREACHABLE: 'Target could not be reached',
};

const greeting = (ctx) => {
    if (!ctx) return 'Run a test in Chaos Lab and I will explain what happened in your project.';
    const proj = ctx.project?.name || 'your project';
    if (ctx.tutor_needed) {
        return `New test result for “${proj}”: ${ctx.injected?.label || 'Injected fault'}. The project did not handle it correctly`
            + `${ctx.code ? ` — the problem is in ${ctx.code.file}, line ${ctx.code.line}` : ''}. `
            + `${ctx.fix?.code ? 'Your code and a suggested fix are shown on the right. ' : ''}`
            + 'Ask me why it failed, how the fix works, or which resilience pattern to learn.';
    }
    if (ctx.handled_correctly) {
        return `“${proj}” handled “${ctx.injected?.label || 'the fault'}” correctly, so nothing needs fixing. Ask me why it passed or how to test it harder.`;
    }
    return `The last test on “${proj}” ended without a verdict (${OUTCOME_LABEL[ctx.outcome] || ctx.outcome || ctx.status || 'Unknown'}). There is nothing to fix yet.`;
};

export default function TutorPage({ setCurrentView, selectedProjectId }) {
    const projectId = selectedProjectId || localStorage.getItem('chaosTutorProjectId') || '';
    const [info, setInfo] = useState(null);
    const [infoError, setInfoError] = useState('');
    const [pinnedRunId, setPinnedRunId] = useState('');
    const [view, setView] = useState({ runId: '', ctx: null, diag: null, session: null, loading: false, error: '' });
    const [retryTick, setRetryTick] = useState(0);
    const [justUpdated, setJustUpdated] = useState(false);

    const [data, setData] = useState({});
    const [liveDiagnosis, setLiveDiagnosis] = useState(false);
    const [followUp, setFollowUp] = useState('');
    const [asking, setAsking] = useState(false);
    const [copied, setCopied] = useState(false);
    const [maxChatHeight, setMaxChatHeight] = useState(null);

    const explanationRef = useRef(null);
    const chatBodyRef = useRef(null);
    const textareaRef = useRef(null);
    const prevRunRef = useRef('');

    const latestDoneId = info?.latest_completed?.id || '';
    const activeRunId = pinnedRunId || latestDoneId;
    const runningNow = info?.latest?.status === 'RUNNING';
    const runningProjectName = info?.project_name || view.ctx?.project?.name || (projectId ? 'Project ' + projectId.slice(0, 8) : 'Your project');
    const runningInjectedError = info?.latest?.fault_label || info?.latest?.experiment_name || view.ctx?.injected?.label || data.title || '';

    // Persisted messages state (restores on mount / page refresh)
    const [messages, setMessages] = useState(() => {
        try {
            const rId = localStorage.getItem('chaosTutorRunId') || '';
            const pId = selectedProjectId || localStorage.getItem('chaosTutorProjectId') || '';
            const key = getChatStorageKey(rId, pId);
            const saved = localStorage.getItem(key);
            if (saved) {
                const parsed = JSON.parse(saved);
                if (Array.isArray(parsed) && parsed.length > 0) return parsed;
            }
        } catch {}
        return [{
            role: 'assistant',
            text: greeting(null),
            time: 'Now'
        }];
    });

    // Auto-adjust chat height to match explanation panel
    useEffect(() => {
        if (!explanationRef.current) return;
        const updateHeight = () => {
            if (explanationRef.current) {
                const explHeight = explanationRef.current.offsetHeight;
                const minHeight = window.innerHeight - 150;
                setMaxChatHeight(Math.max(explHeight, minHeight));
            }
        };
        updateHeight();
        let ro = null;
        if (typeof ResizeObserver !== 'undefined') {
            ro = new ResizeObserver(() => updateHeight());
            ro.observe(explanationRef.current);
        }
        window.addEventListener('resize', updateHeight);
        return () => {
            if (ro) ro.disconnect();
            window.removeEventListener('resize', updateHeight);
        };
    }, [data, view]);

    // Smooth scroll chat body to bottom when messages or asking state changes
    useEffect(() => {
        if (chatBodyRef.current) {
            chatBodyRef.current.scrollTo({
                top: chatBodyRef.current.scrollHeight,
                behavior: 'smooth'
            });
        }
    }, [messages, asking]);

    // Auto-expand textarea as user types (moving edit text height smoothly)
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            const scrollH = textareaRef.current.scrollHeight;
            textareaRef.current.style.height = `${Math.min(Math.max(scrollH, 24), 140)}px`;
        }
    }, [followUp]);

    // Persist chat messages whenever they change
    useEffect(() => {
        if (!messages || messages.length === 0) return;
        try {
            const key = getChatStorageKey(activeRunId, projectId);
            localStorage.setItem(key, JSON.stringify(messages));
        } catch {}
    }, [messages, activeRunId, projectId]);

    // Continuously watch for fresh runs from Chaos Lab
    useEffect(() => {
        setInfo(null);
        setPinnedRunId('');
        prevRunRef.current = '';
        if (!projectId) return undefined;
        let cancelled = false;
        const poll = async () => {
            if (document.hidden) return;
            try {
                const r = await getProjectLatestRun(projectId);
                if (cancelled) return;
                setInfo(prev => (JSON.stringify(prev) === JSON.stringify(r) ? prev : r));
                setInfoError('');
            } catch (e) {
                if (!cancelled) setInfoError(e.message || 'Could not reach the backend.');
            }
        };
        poll();
        const timer = setInterval(poll, 2500);
        window.addEventListener('chaosTutorRunChanged', poll);
        return () => { cancelled = true; clearInterval(timer); window.removeEventListener('chaosTutorRunChanged', poll); };
    }, [projectId]);

    // Load active run diagnosis & context whenever activeRunId changes
    useEffect(() => {
        if (!activeRunId) {
            setView({ runId: '', ctx: null, diag: null, session: null, loading: false, error: '' });
            setData({});
            setLiveDiagnosis(false);
            return undefined;
        }
        let cancelled = false;
        setView(v => ({ ...v, loading: true, error: '' }));
        (async () => {
            try {
                const [ctx, diag, session] = await Promise.all([
                    getTutorContext(activeRunId).catch(() => null),
                    getRunDiagnosis(activeRunId).catch(() => null),
                    getTutor(activeRunId).catch(() => null),
                ]);
                if (cancelled) return;
                localStorage.setItem('chaosTutorRunId', activeRunId);
                setView({ runId: activeRunId, ctx, diag, session, loading: false, error: '' });
                setLiveDiagnosis(true);

                const outcome = session?.explanation?.outcome || diag?.outcome || ctx?.outcome || null;
                const isProblem = session?.explanation?.is_problem ?? (ctx ? ctx.tutor_needed : !!diag?.failure);
                const evidence = diag?.evidence;
                const evidenceText = typeof evidence === 'string'
                    ? evidence
                    : Array.isArray(evidence) ? evidence.join('\\n') : (evidence ? JSON.stringify(evidence, null, 2) : '');

                // Real dynamic reason fields
                const rootCause = diag?.root_cause || diag?.failure || session?.explanation?.what_happened || '';
                const injectedDesc = ctx?.injected?.description || '';
                const impact = diag?.impact || session?.explanation?.why_it_matters || '';
                const locationFile = ctx?.code?.file || '';
                const locationLine = ctx?.code?.line || '';
                const traceLines = evidenceText ? evidenceText.split('\\n').map(l => l.trim()).filter(Boolean) : [];

                // Real dynamic fix fields
                const fixAction = diag?.recommended_fix || '';
                const fixExplanation = ctx?.fix?.llm_explanation || '';
                const fixNotes = Array.isArray(ctx?.fix?.notes) ? ctx.fix.notes : [];
                const suggestedActions = Array.isArray(session?.explanation?.suggested_actions) ? session.explanation.suggested_actions : [];
                const fixImports = [ ...(ctx?.fix?.imports || []), ...(ctx?.fix?.extras || []) ].filter(Boolean);

                // Real dynamic pattern fields
                const patternTitle = diag?.resilience_pattern || session?.explanation?.concept || '';
                const patternDesc = ctx?.fix?.title || fixExplanation || fixAction || '';
                const fragileCode = ctx?.code?.snippet || ctx?.code?.raw_snippet || '';
                const fragileFile = ctx?.code?.file ? `${ctx.code.file}${ctx.code.line ? ` · line ${ctx.code.line}` : ''}` : '';
                const resilientCode = ctx?.fix?.code || '';
                const resilientFile = ctx?.fix?.file ? `${ctx.fix.file}${ctx.fix.method ? ` · ${ctx.fix.method}` : ''}` : '';

                setData({
                    title: ctx?.injected?.label || diag?.failure || diag?.title || session?.explanation?.what_happened || '',
                    outcome,
                    isProblem,
                    rootCause,
                    injectedDesc,
                    impact,
                    locationFile,
                    locationLine,
                    traceLines,
                    fixAction,
                    fixExplanation,
                    fixNotes,
                    suggestedActions,
                    fixImports,
                    patternTitle,
                    patternDesc,
                    fragileCode,
                    fragileFile,
                    resilientCode,
                    resilientFile,
                });

                const chatStorageKey = getChatStorageKey(activeRunId, projectId);
                let savedChat = null;
                try {
                    const raw = localStorage.getItem(chatStorageKey);
                    if (raw) savedChat = JSON.parse(raw);
                } catch {}

                if (Array.isArray(savedChat) && savedChat.length > 0) {
                    setMessages(savedChat);
                } else {
                    const initial = [{
                        role: 'assistant',
                        text: greeting(ctx),
                        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                    }];
                    setMessages(initial);
                    try { localStorage.setItem(chatStorageKey, JSON.stringify(initial)); } catch {}
                }

                if (prevRunRef.current && prevRunRef.current !== activeRunId && !pinnedRunId) {
                    setJustUpdated(true);
                    setTimeout(() => setJustUpdated(false), 5000);
                }
                prevRunRef.current = activeRunId;
            } catch (e) {
                if (!cancelled) setView({ runId: '', ctx: null, diag: null, session: null, loading: false, error: e.message || 'Could not load this run.' });
            }
        })();
        return () => { cancelled = true; };
    }, [activeRunId, retryTick, projectId]);

    const handleAskTutor = async (explicitQuestion = null) => {
        const question = (explicitQuestion ?? followUp).trim();
        if (!question || asking) return;
        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        setFollowUp('');
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
        }
        setMessages(prev => [...prev, { role: 'user', text: question, time: timeStr }]);
        setAsking(true);

        try {
            const history = messages.slice(-8).map(({ role, text }) => ({ role, text }));
            let answer = null;

            // 1. Direct call to ai_tutor_backend Flask service (port 5000)
            try {
                const fault = view.ctx?.injected?.label || view.ctx?.injected?.type || view.diag?.failure || data.title || '';
                const contextStr = [
                    view.ctx?.project?.name ? `Project: ${view.ctx.project.name}` : '',
                    view.ctx?.injected?.label ? `Injected Fault: ${view.ctx.injected.label}` : '',
                    view.ctx?.code?.file ? `Problem Location: ${view.ctx.code.file}, line ${view.ctx.code.line}` : '',
                    view.ctx?.code?.snippet ? `Current Code:\\n${view.ctx.code.snippet}` : '',
                    view.ctx?.fix?.code ? `Suggested Fix:\\n${view.ctx.fix.code}` : '',
                    view.diag?.root_cause ? `Root Cause: ${view.diag.root_cause}` : '',
                    view.diag?.affected_component ? `Affected Component: ${view.diag.affected_component}` : '',
                    view.diag?.recommended_fix ? `Recommended Fix: ${view.diag.recommended_fix}` : '',
                    view.diag?.evidence ? `Evidence: ${Array.isArray(view.diag.evidence) ? view.diag.evidence.join('; ') : view.diag.evidence}` : '',
                ].filter(Boolean).join('\\n\\n');

                const abortCtrl = new AbortController();
                const timeoutId = setTimeout(() => abortCtrl.abort(), 12000);
                const resp = await fetch('http://127.0.0.1:5000/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question, fault, context: contextStr, history }),
                    signal: abortCtrl.signal,
                });
                clearTimeout(timeoutId);
                if (resp.ok) {
                    const d = await resp.json();
                    if (d?.answer) answer = d.answer;
                }
            } catch {}

            // 2. Query through main backend /tutor/{id}/ask (routes through ai_tutor_backend with rotated keys)
            if (!answer) {
                if (view.runId) {
                    let sessionId = view.session?.tutor_session_id;
                    if (!sessionId) sessionId = (await getTutor(view.runId))?.tutor_session_id;
                    if (sessionId) {
                        const result = await askTutor(sessionId, question, history);
                        answer = result?.answer || result?.feedback || null;
                    }
                }
            }

            if (!answer) {
                answer = "I could not generate an answer right now. Make sure the backend server is active.";
            }

            const responseTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            setMessages(prev => [...prev, { role: 'assistant', text: answer, time: responseTime }]);
        } catch (error) {
            console.error('Ask Tutor failed:', error);
            const timeNow = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            setMessages(prev => [...prev, { role: 'assistant', text: "Couldn't reach the tutor backend right now. Make sure the backend is running.", time: timeNow }]);
        } finally {
            setAsking(false);
        }
    };

    const handleClearChat = () => {
        const initial = [{
            role: 'assistant',
            text: greeting(view.ctx),
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }];
        setMessages(initial);
        try {
            const key = getChatStorageKey(activeRunId, projectId);
            localStorage.setItem(key, JSON.stringify(initial));
        } catch {}
    };

    const handleFollowUpKeyDown = (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            handleAskTutor();
        }
    };

    const copyCode = () => {
        if (!data.resilientCode) return;
        navigator.clipboard.writeText(data.resilientCode);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const quickQuestions = view.ctx?.tutor_needed
        ? ['Why did my code fail?', 'Explain the fix line by line', 'How do I verify the fix?']
        : view.ctx?.handled_correctly
            ? ['Why did this pass?', 'What should I test next?']
            : ['Why did this test fail?', 'How does the circuit breaker pattern work?'];

    const outcomeColor = view.ctx?.tutor_needed ? '#ef4444' : (view.ctx?.handled_correctly ? '#10b981' : '#f59e0b');

    // Dynamic presence checks: a block appears ONLY if it has specific real data for this error
    const hasReasonData = !!(data.rootCause || data.injectedDesc || data.impact || data.locationFile || (data.traceLines && data.traceLines.length > 0));
    const hasFixData = !!(data.fixAction || data.fixExplanation || (data.fixNotes && data.fixNotes.length > 0) || (data.suggestedActions && data.suggestedActions.length > 0) || (data.fixImports && data.fixImports.length > 0));
    const hasPatternData = !!(data.patternTitle || data.resilientCode || data.fragileCode);

    return (
        <div className="chaos-tutor-view">
            <style>{`
"""

part2 = """
            `}</style>

            {/* LIVE SPINNER NOTIFICATION BANNER: Tells which project is running & the injected error */}
            {runningNow && (
                <div className="chaos-runningBanner">
                    <div className="chaos-runningSpinnerWrapper">
                        <Loader2 size={20} className="spin" color="#818cf8" />
                    </div>
                    <div className="chaos-runningContent">
                        <div className="chaos-runningHeadline">
                            <span className="chaos-runningBadge">TEST IN PROGRESS</span>
                            Running chaos experiment on project <strong>{runningProjectName}</strong>
                        </div>
                        <div className="chaos-runningSub">
                            Injected Error: <span className="chaos-faultHighlight">{runningInjectedError || 'Fault Injection'}</span> — Monitoring failure points in real-time. This page updates automatically.
                        </div>
                    </div>
                </div>
            )}

            {/* Top Project & Run Status Bar */}
            <div className="chaos-topBar">
                {runningProjectName && (
                    <span className="chaos-badge" style={{ background: 'rgba(99,102,241,0.14)', border: '1px solid rgba(99,102,241,0.35)', color: '#c7d2fe' }}>
                        <Folder size={13} /> {runningProjectName}
                    </span>
                )}
                {activeRunId && (
                    <span className="chaos-badge" style={{ background: `${outcomeColor}22`, border: `1px solid ${outcomeColor}66`, color: outcomeColor }}>
                        RUN-{String(activeRunId).slice(0, 8)} · {OUTCOME_LABEL[data.outcome] || data.outcome || 'COMPLETED'}
                    </span>
                )}
                {runningNow ? (
                    <span className="chaos-runningPill">
                        <Loader2 size={13} className="spin" />
                        <span>Running on <strong>{runningProjectName}</strong>: <em style={{ color: '#fbbf24' }}>{runningInjectedError || 'Active Test'}</em></span>
                    </span>
                ) : (
                    liveDiagnosis && (
                        <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 700, color: '#34d399' }}>
                            <Sparkles size={12} /> LIVE
                        </span>
                    )
                )}
                {justUpdated && (
                    <span style={{ fontSize: 11, fontWeight: 700, color: '#fbbf24', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)', padding: '3px 10px', borderRadius: 6 }}>
                        Updated with your newest test
                    </span>
                )}

                {info?.recent?.length > 1 && (
                    <select
                        value={pinnedRunId}
                        onChange={e => setPinnedRunId(e.target.value)}
                        aria-label="Choose a test result"
                        style={{ marginLeft: 'auto', background: 'rgba(11,14,22,0.9)', color: '#cbd5e1', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8, padding: '6px 10px', fontSize: 12, maxWidth: 300, outline: 'none' }}
                    >
                        <option value="">Newest result (automatic)</option>
                        {info.recent.map(r => (
                            <option key={r.id} value={r.id}>{r.experiment_name || 'Test'} — {OUTCOME_LABEL[r.outcome] || r.outcome}</option>
                        ))}
                    </select>
                )}
            </div>

            {/* Loading Indicator */}
            {view.loading && !view.ctx && (
                <div className="chaos-loadingNotice">
                    <Loader2 size={15} className="spin" color="#818cf8" />
                    <span>Loading test diagnosis for <strong>{runningProjectName}</strong> ({runningInjectedError || 'Experiment'})…</span>
                </div>
            )}

            {/* Empty State when first test is running on a project */}
            {projectId && !activeRunId && runningNow && (
                <div className="glass-card" style={{ padding: 36, textAlign: 'center', margin: '0 auto 24px', maxWidth: 640 }}>
                    <div style={{ display: 'inline-flex', padding: 14, borderRadius: '50%', background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(129,140,248,0.25)', marginBottom: 14 }}>
                        <Loader2 size={32} className="spin" color="#818cf8" />
                    </div>
                    <h2 style={{ fontSize: 18, marginBottom: 8, color: '#f3f4f6' }}>Chaos Test Running on “{runningProjectName}”</h2>
                    <div style={{ fontSize: 13, color: '#fbbf24', fontWeight: 600, marginBottom: 12 }}>
                        Injected Error: {runningInjectedError || 'Chaos Fault'}
                    </div>
                    <p style={{ color: '#94a3b8', fontSize: 13, lineHeight: 1.6, maxWidth: 500, margin: '0 auto' }}>
                        The test is currently injecting this fault into your application. As soon as the service responds or fails, the AI Tutor will immediately present the root cause, exact code lines, and resilience patch here.
                    </p>
                </div>
            )}

            {/* Main 2-Column Equal Workspace: Chat Left, AI Tutor Right */}
            <div className="chaos-workspace">

                {/* LEFT: AI TUTOR CHAT PANEL */}
                <div
                    className="chaos-panel chaos-chatPanel"
                    style={{
                        maxHeight: maxChatHeight ? `${maxChatHeight}px` : undefined
                    }}
                >
                    <div className="chaos-panelHeader">
                        <div className="chaos-panelTitle">
                            <div className="chaos-titleIcon">
                                <Bot size={20} />
                            </div>
                            <div>
                                <h2>AI TUTOR CHAT</h2>
                                <p>Your AI mentor for understanding failures and building resilient apps.</p>
                            </div>
                        </div>

                        <button
                            className="chaos-clearButton"
                            onClick={handleClearChat}
                            title="Clear conversation"
                        >
                            <Trash2 size={13} />
                            Clear Chat
                        </button>
                    </div>

                    <div className="chaos-chatBody" ref={chatBodyRef}>
                        {messages.map((message, index) => (
                            <div
                                key={index}
                                className={message.role === 'user' ? 'chaos-userMessage' : 'chaos-aiMessage'}
                            >
                                {message.role === 'user' ? (
                                    <>
                                        <small>{message.time || 'Now'}</small>
                                        <div className="chaos-userBubble">
                                            {message.text}
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        <div className="chaos-smallRobot">
                                            <Bot size={16} />
                                        </div>
                                        <div className="chaos-answerBox">
                                            <div className="chaos-messageTop">
                                                <b>AI Tutor</b>
                                                <small>{message.time || 'Now'}</small>
                                            </div>
                                            <p style={{ whiteSpace: 'pre-wrap' }}>{message.text}</p>
                                        </div>
                                    </>
                                )}
                            </div>
                        ))}

                        {asking && (
                            <div className="chaos-aiMessage">
                                <div className="chaos-smallRobot">
                                    <Bot size={16} />
                                </div>
                                <div className="chaos-loadingBox">
                                    <div className="chaos-messageTop">
                                        <b>AI Tutor</b>
                                        <small>Now</small>
                                    </div>
                                    <p>Analyzing failure points and synthesizing guidance...</p>
                                    <div className="chaos-dots">
                                        <i></i><i></i><i></i><i></i>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Quick suggestion chips */}
                    {quickQuestions.length > 0 && (
                        <div className="chaos-quickQuestions">
                            {quickQuestions.map(q => (
                                <button
                                    key={q}
                                    type="button"
                                    className="chaos-quickChip"
                                    onClick={() => handleAskTutor(q)}
                                    disabled={asking}
                                >
                                    {q}
                                </button>
                            ))}
                        </div>
                    )}

                    {/* Dynamic Auto-Expanding Edit Text Input */}
                    <div className="chaos-chatInput">
                        <textarea
                            ref={textareaRef}
                            className="chaos-chatTextarea"
                            placeholder="Ask about the failure, fix, or code... (Shift+Enter for new line)"
                            value={followUp}
                            onChange={(e) => setFollowUp(e.target.value)}
                            onKeyDown={handleFollowUpKeyDown}
                            disabled={asking}
                            rows={1}
                        />
                        <button
                            onClick={() => handleAskTutor()}
                            disabled={!followUp.trim() || asking}
                            title="Send question (Enter)"
                        >
                            {asking ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
                        </button>
                    </div>
                </div>

                {/* RIGHT: AI TUTOR EXPLANATION PANEL */}
                <div className="chaos-panel chaos-explanationPanel" ref={explanationRef}>
                    <div className="chaos-explanationHeader">
                        <div>
                            <h2>
                                <Sparkles size={16} color="#a5b4fc" />
                                AI TUTOR EXPLANATION
                            </h2>
                        </div>
                        <span className="chaos-generated">
                            {runningNow
                                ? `Running on ${runningProjectName}…`
                                : (liveDiagnosis
                                    ? `RUN-${String(activeRunId || '').slice(0, 8)} · LIVE`
                                    : `Generated at ${new Date().toLocaleTimeString()}`)}
                        </span>
                    </div>

                    {/* Running Notice in Explanation Panel */}
                    {runningNow && (
                        <div className="chaos-activeTestAlert" style={{ margin: '14px 18px 0 18px' }}>
                            <Loader2 size={15} className="spin" color="#a5b4fc" />
                            <span>
                                Active test running on <strong>{runningProjectName}</strong> with <strong>{runningInjectedError || 'Injected Fault'}</strong>. Results will refresh live.
                            </span>
                        </div>
                    )}

                    <div className="chaos-explanationContent">
                        {/* 1. DYNAMIC REASON BLOCK: Appears ONLY if real reason data exists for this specific error */}
                        {hasReasonData && (
                            <div className="chaos-reasonCard">
                                <h3>⚠️ Reason</h3>
                                {data.rootCause && (
                                    <p style={{ marginBottom: '8px' }}>
                                        <strong style={{ color: '#f3f4f6' }}>Root cause:</strong> {data.rootCause}
                                    </p>
                                )}
                                {data.injectedDesc && (
                                    <p style={{ marginBottom: '8px', color: '#cbd5e1' }}>
                                        {data.injectedDesc}
                                    </p>
                                )}
                                {data.impact && (
                                    <div style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: 8, padding: '8px 12px', marginBottom: '10px', display: 'flex', gap: 6, alignItems: 'center' }}>
                                        <span style={{ color: '#f59e0b', fontSize: 13 }}>⚠</span>
                                        <span style={{ fontSize: 12, color: '#f59e0b', fontWeight: 500 }}>
                                            <strong>Impact:</strong> {data.impact}
                                        </span>
                                    </div>
                                )}
                                {data.locationFile && (
                                    <p style={{ fontSize: 12, color: '#a5b4fc', marginBottom: '8px' }}>
                                        Location in code: <code style={{ background: 'rgba(255,255,255,0.08)', padding: '2px 6px', borderRadius: 4, fontFamily: 'monospace' }}>{data.locationFile}{data.locationLine ? `:${data.locationLine}` : ''}</code>
                                    </p>
                                )}
                                {data.traceLines && data.traceLines.length > 0 && (
                                    <div style={{ marginTop: '8px', background: 'rgba(4,6,12,0.6)', borderRadius: 8, padding: '10px 14px', overflowX: 'auto' }}>
                                        <div style={{ fontSize: 10, fontWeight: 700, color: '#64748b', letterSpacing: '0.6px', textTransform: 'uppercase', marginBottom: 6 }}>Error Trace / Evidence</div>
                                        {data.traceLines.slice(0, 6).map((line, idx) => (
                                            <div key={idx} style={{ fontFamily: 'monospace', fontSize: 11, lineHeight: 1.6, color: idx === 0 ? '#f87171' : '#94a3b8', whiteSpace: 'pre' }}>
                                                {line}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* 2. DYNAMIC FIX BLOCK: Appears ONLY if real recommended fix data exists for this specific error */}
                        {hasFixData && (
                            <div className="chaos-fixCard">
                                <h3>🛠 Fix</h3>
                                {data.fixAction && (
                                    <p style={{ color: '#e2e8f0', fontWeight: 500, marginBottom: '8px' }}>
                                        ✓ {data.fixAction}
                                    </p>
                                )}
                                {data.fixExplanation && (
                                    <p style={{ color: '#cbd5e1', fontSize: 12, lineHeight: 1.6, marginBottom: '8px' }}>
                                        {data.fixExplanation}
                                    </p>
                                )}
                                {data.fixNotes && data.fixNotes.length > 0 && (
                                    <ul style={{ margin: '6px 0 10px', paddingLeft: 18, color: '#cbd5e1', fontSize: 12, lineHeight: 1.6 }}>
                                        {data.fixNotes.map((note, idx) => (
                                            <li key={idx} style={{ marginBottom: 4 }}>{note}</li>
                                        ))}
                                    </ul>
                                )}
                                {data.suggestedActions && data.suggestedActions.length > 0 && (
                                    <div style={{ marginTop: 8 }}>
                                        {data.suggestedActions.map((act, idx) => (
                                            <p key={idx} style={{ color: '#34d399', fontSize: 12, marginBottom: 4 }}>
                                                ✓ {act}
                                            </p>
                                        ))}
                                    </div>
                                )}
                                {data.fixImports && data.fixImports.length > 0 && (
                                    <div style={{ marginTop: 10, background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.22)', borderRadius: 8, padding: '8px 12px' }}>
                                        <div style={{ fontSize: 10, fontWeight: 700, color: '#a5b4fc', textTransform: 'uppercase', marginBottom: 4 }}>Required Imports / Extras</div>
                                        <pre style={{ margin: 0, fontSize: 11, fontFamily: 'monospace', color: '#c7d2fe', whiteSpace: 'pre-wrap' }}>{data.fixImports.join('\\n')}</pre>
                                    </div>
                                )}

                                <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                                    <button className="chaos-actionBtn" onClick={() => setCurrentView?.('ide')}>
                                        <Code2 size={13} /> Open Cloud IDE
                                    </button>
                                    <button className="chaos-actionBtn" onClick={() => setCurrentView?.('chaos-lab')}>
                                        <Zap size={13} /> Re-run in Chaos Lab
                                    </button>
                                </div>
                            </div>
                        )}

                        {/* 3. DYNAMIC PATTERN BLOCK: Appears ONLY if real resilience pattern or code exists for this specific error */}
                        {hasPatternData && (
                            <div className="chaos-patternCard">
                                {/* Header */}
                                <div className="chaos-patternHeader">
                                    <div className="chaos-patternIcon">🛡</div>
                                    <div>
                                        <h3>{data.patternTitle || 'Recommended Resilience Pattern'}</h3>
                                        {data.patternDesc && <p>{data.patternDesc}</p>}
                                    </div>
                                </div>

                                {/* Code Diff: Shows user's real fragile code and generated resilient fix code */}
                                {(data.fragileCode || data.resilientCode) && (
                                    <div className="chaos-codeDiff" style={{ gridTemplateColumns: (data.fragileCode && data.resilientCode) ? '1fr 1fr' : '1fr' }}>
                                        {data.fragileCode && (
                                            <div className="chaos-diffPane chaos-diffFragile">
                                                <div className="chaos-diffLabel">
                                                    <span>Fragile ({data.fragileFile || 'Your code'})</span>
                                                    <span>✕</span>
                                                </div>
                                                <pre style={{ margin: 0, padding: '12px 14px', overflowX: 'auto', fontFamily: 'monospace', fontSize: '11.5px', lineHeight: 1.6, color: '#f87171' }}>{data.fragileCode}</pre>
                                            </div>
                                        )}

                                        {data.resilientCode && (
                                            <div className="chaos-diffPane chaos-diffResilient">
                                                <div className="chaos-diffLabel">
                                                    <span>Resilient ({data.resilientFile || 'Suggested fix'})</span>
                                                    <span>✓</span>
                                                </div>
                                                <pre style={{ margin: 0, padding: '12px 14px', overflowX: 'auto', fontFamily: 'monospace', fontSize: '11.5px', lineHeight: 1.6, color: '#34d399' }}>{data.resilientCode}</pre>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* Footer with Copy button */}
                                {data.resilientCode && (
                                    <div className="chaos-patternFooter">
                                        <button
                                            className="chaos-copyCode"
                                            onClick={copyCode}
                                            title="Copy resilient code"
                                            style={{ position: 'static' }}
                                        >
                                            {copied ? <><Check size={12} color="#34d399" /> Copied</> : <><Copy size={12} /> Copy Pattern</>}
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* CASE: Project handled the fault correctly (tutor not needed) */}
                        {view.ctx?.handled_correctly && (
                            <div className="chaos-reasonCard" style={{ borderColor: 'rgba(16,185,129,0.35)', background: 'rgba(16,185,129,0.06)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                                    <ShieldCheck size={20} color="#10b981" />
                                    <span style={{ fontSize: 16, fontWeight: 700, color: '#34d399' }}>Handled correctly — No fix needed</span>
                                </div>
                                <p style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.6, margin: 0 }}>
                                    “{runningProjectName}” responded to this error the way a resilient service should. No failure was observed and no fix is required.
                                </p>
                                {data.fragileCode && (
                                    <div style={{ marginTop: 12 }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: '#34d399', marginBottom: 6 }}>Verified code in {data.fragileFile || 'project'}:</div>
                                        <pre style={{ margin: 0, padding: 12, borderRadius: 8, background: 'rgba(4,6,12,0.6)', border: '1px solid rgba(16,185,129,0.25)', color: '#a7f3d0', fontSize: 11.5, fontFamily: 'monospace' }}>{data.fragileCode}</pre>
                                    </div>
                                )}
                                <div style={{ marginTop: 14 }}>
                                    <button className="chaos-actionBtn" onClick={() => setCurrentView?.('chaos-lab')}>
                                        <Zap size={13} /> Run another test in Chaos Lab
                                    </button>
                                </div>
                            </div>
                        )}

                        {/* EMPTY STATE: Neither reason, fix, pattern, nor handled */}
                        {!hasReasonData && !hasFixData && !hasPatternData && !view.ctx?.handled_correctly && !runningNow && (
                            <div style={{ textAlign: 'center', padding: '40px 20px', color: '#94a3b8', fontSize: 13 }}>
                                <p style={{ marginBottom: 12 }}>No experiment diagnosis selected or available yet.</p>
                                <button className="chaos-actionBtn" onClick={() => setCurrentView?.('chaos-lab')}>
                                    <Zap size={13} /> Go to Chaos Lab
                                </button>
                            </div>
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}
"""

full_content = part1 + enhanced_css + part2

with open(target_file, "w", encoding="utf-8") as f:
    f.write(full_content)

print(f"Successfully generated new TutorPage.jsx ({len(full_content)} bytes) at {target_file}")
