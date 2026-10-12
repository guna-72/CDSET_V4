import { friendlyError } from '../utils/friendlyError';
import React, { useState, useEffect, useRef } from 'react';
import {
    Sparkles, Send, Bot, UserRound, Loader2, Trash2, Copy, Check,
    ShieldCheck, Code2, AlertTriangle, Zap, RotateCcw, Folder
} from 'lucide-react';
import {
    getRunDiagnosis, getTutor, askTutor, getTutorContext,
    getProjectLatestRun, listRuns
} from '../api';
import { getEffectiveApiKey } from '../utils/apiKeys';
import SpotlightCard from '../components/SpotlightCard';

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

const buildContextStr = (ctx, diag) => {
    return [
        ctx?.project?.name ? `Project: ${ctx.project.name}` : '',
        ctx?.injected?.label ? `Injected Fault: ${ctx.injected.label}` : '',
        ctx?.code?.file ? `Problem Location: ${ctx.code.file}${ctx?.code?.line ? `, line ${ctx.code.line}` : ''}` : '',
        ctx?.code?.snippet ? `Current Code:\n${ctx.code.snippet}` : '',
        ctx?.fix?.code ? `Suggested Fix:\n${ctx.fix.code}` : '',
        diag?.root_cause ? `Root Cause: ${diag.root_cause}` : '',
        diag?.affected_component ? `Affected Component: ${diag.affected_component}` : '',
        diag?.recommended_fix ? `Recommended Fix: ${diag.recommended_fix}` : '',
        diag?.evidence ? `Evidence: ${Array.isArray(diag.evidence) ? diag.evidence.join('; ') : diag.evidence}` : '',
    ].filter(Boolean).join('\n\n');
};

const requestAiTutorResponse = async ({ question, fault, contextStr, history = [], runId = '', sessionId = '' }) => {
    let answer = null;

    // Check setting for API key first; if present, use that; else ai_tutor_backend falls back to .env
    const settingGeminiKey = getEffectiveApiKey('gemini') || getEffectiveApiKey('auto');

    // 1. Direct call to ai_tutor_backend Flask service (port 5000)
    try {
        const abortCtrl = new AbortController();
        const timeoutId = setTimeout(() => abortCtrl.abort(), 12000);
        const headers = { 'Content-Type': 'application/json' };
        if (settingGeminiKey) {
            headers['X-API-Key'] = settingGeminiKey;
        }
        const resp = await fetch('http://127.0.0.1:5000/api/chat', {
            method: 'POST',
            headers,
            body: JSON.stringify({
                question,
                fault,
                context: contextStr,
                history,
                ...(settingGeminiKey ? { api_key: settingGeminiKey } : {})
            }),
            signal: abortCtrl.signal,
        });
        clearTimeout(timeoutId);
        if (resp.ok) {
            const d = await resp.json();
            const isPlaceholder = /^\s*(gemini api keys are not configured|i am currently unable to reach the ai model)/i.test(String(d?.answer || ''));
            if (d?.answer && !isPlaceholder) answer = d.answer;
        }
    } catch {}

    // 2. Query through main backend /tutor/{id}/ask (routes through ai_tutor_backend direct python import)
    if (!answer && runId) {
        try {
            let activeSessionId = sessionId;
            if (!activeSessionId) activeSessionId = (await getTutor(runId))?.tutor_session_id;
            if (activeSessionId) {
                const result = await askTutor(activeSessionId, question, history);
                const isPlaceholder = /^\s*(gemini api keys are not configured|i am currently unable to reach the ai model)/i.test(String(result?.answer || ''));
                if (result?.answer && !isPlaceholder) {
                    answer = result.answer;
                } else if (result?.feedback && !isPlaceholder) {
                    answer = result.feedback;
                }
            }
        } catch {}
    }

    return answer;
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
    const [copiedError, setCopiedError] = useState(false);
    const [copiedFix, setCopiedFix] = useState(false);
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
            if (saved !== null) {
                const parsed = JSON.parse(saved);
                if (Array.isArray(parsed)) return parsed;
            }
        } catch {}
        return [];
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
                if (!cancelled) setInfoError(friendlyError(e) || 'Could not reach the backend.');
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
                    : Array.isArray(evidence) ? evidence.join('\n') : (evidence ? JSON.stringify(evidence, null, 2) : '');

                // Real dynamic reason fields
                const rootCause = diag?.root_cause || diag?.failure || session?.explanation?.what_happened || '';
                const injectedDesc = ctx?.injected?.description || '';
                const impact = diag?.impact || session?.explanation?.why_it_matters || '';
                const locationFile = ctx?.code?.file || '';
                const locationLine = ctx?.code?.line || '';
                const traceLines = evidenceText ? evidenceText.split('\n').map(l => l.trim()).filter(Boolean) : [];

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
                let hasSavedChat = false;
                try {
                    const raw = localStorage.getItem(chatStorageKey);
                    if (raw !== null) {
                        savedChat = JSON.parse(raw);
                        hasSavedChat = true;
                    }
                } catch {}

                if (hasSavedChat && Array.isArray(savedChat)) {
                    // Respect the user's stored conversation (including [] if they cleared the chat!)
                    setMessages(savedChat);
                } else if (activeRunId && (ctx?.tutor_needed || ctx?.handled_correctly || diag)) {
                    // Brand new conversation for this test result: fetch initial message from ai_tutor_backend
                    const faultLabel = ctx?.injected?.label || ctx?.injected?.type || diag?.failure || '';
                    const projectName = ctx?.project?.name || (projectId ? 'Project ' + projectId.slice(0, 8) : 'the project');
                    const isSuccess = ctx?.handled_correctly;

                    const promptQuestion = isSuccess
                        ? `Introduce yourself as the AI Tutor. The project "${projectName}" was tested with "${faultLabel}" and handled it safely and correctly with no errors. Give a brief, encouraging 2-3 sentence overview of this test and invite the student to ask questions about how it was handled or how to test it further.`
                        : `Introduce yourself as the AI Tutor. A chaos test "${faultLabel}" was run on project "${projectName}" and an error occurred. Provide an educational, concise 2-4 sentence opening breakdown of what happened and why, and invite the student to ask about the root cause, fix, or resilience pattern.`;

                    const contextStr = buildContextStr(ctx, diag);

                    setAsking(true);
                    requestAiTutorResponse({
                        question: promptQuestion,
                        fault: faultLabel,
                        contextStr,
                        history: [],
                        runId: activeRunId,
                        sessionId: session?.tutor_session_id
                    }).then((aiGreeting) => {
                        if (cancelled) return;
                        const initialText = aiGreeting || (isSuccess
                            ? `Hello! I am your AI Tutor. “${projectName}” handled “${faultLabel || 'the fault'}” correctly with no errors. Ask me why it passed or how to test it harder.`
                            : `Hello! I am your AI Tutor. We ran “${faultLabel || 'a resilience test'}” on “${projectName}” and detected a failure point. Ask me why it failed, how the suggested fix works, or what resilience pattern applies here.`);

                        const initial = [{
                            role: 'assistant',
                            text: initialText,
                            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        }];
                        setMessages(initial);
                        try { localStorage.setItem(chatStorageKey, JSON.stringify(initial)); } catch {}
                    }).catch(() => {
                        if (cancelled) return;
                        const initial = [{
                            role: 'assistant',
                            text: `Hello! I am your AI Tutor for “${projectName}”. Ask me anything about the test results, failure causes, or resilience patterns.`,
                            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        }];
                        setMessages(initial);
                        try { localStorage.setItem(chatStorageKey, JSON.stringify(initial)); } catch {}
                    }).finally(() => {
                        if (!cancelled) setAsking(false);
                    });
                } else {
                    setMessages([]);
                }

                if (prevRunRef.current && prevRunRef.current !== activeRunId && !pinnedRunId) {
                    setJustUpdated(true);
                    setTimeout(() => setJustUpdated(false), 5000);
                }
                prevRunRef.current = activeRunId;
            } catch (e) {
                if (!cancelled) setView({ runId: '', ctx: null, diag: null, session: null, loading: false, error: friendlyError(e) || 'Could not load this run.' });
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
        const updatedMessages = [...messages, { role: 'user', text: question, time: timeStr }];
        setMessages(updatedMessages);
        setAsking(true);

        try {
            const history = messages.slice(-8).map(({ role, text }) => ({ role, text }));
            const fault = view.ctx?.injected?.label || view.ctx?.injected?.type || view.diag?.failure || data.title || '';
            const contextStr = buildContextStr(view.ctx, view.diag);

            let answer = await requestAiTutorResponse({
                question,
                fault,
                contextStr,
                history,
                runId: view.runId,
                sessionId: view.session?.tutor_session_id
            });

            if (!answer) {
                answer = "I could not generate an answer right now. Make sure the AI Tutor backend service is running.";
            }

            const responseTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const finalMessages = [...updatedMessages, { role: 'assistant', text: answer, time: responseTime }];
            setMessages(finalMessages);
            try {
                const key = getChatStorageKey(activeRunId, projectId);
                localStorage.setItem(key, JSON.stringify(finalMessages));
            } catch {}
        } catch (error) {
            console.error('Ask Tutor failed:', error);
            const timeNow = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const finalMessages = [...updatedMessages, { role: 'assistant', text: "Couldn't reach the AI Tutor backend right now. Make sure the service is running.", time: timeNow }];
            setMessages(finalMessages);
            try {
                const key = getChatStorageKey(activeRunId, projectId);
                localStorage.setItem(key, JSON.stringify(finalMessages));
            } catch {}
        } finally {
            setAsking(false);
        }
    };

    const handleClearChat = () => {
        setMessages([]);
        try {
            const key = getChatStorageKey(activeRunId, projectId);
            localStorage.setItem(key, JSON.stringify([]));
        } catch {}
    };

    const handleFollowUpKeyDown = (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            handleAskTutor();
        }
    };

    const copyErrorCode = () => {
        if (!data.fragileCode) return;
        navigator.clipboard.writeText(data.fragileCode);
        setCopiedError(true);
        setTimeout(() => setCopiedError(false), 2000);
    };

    const copyFixCode = () => {
        if (!data.resilientCode) return;
        navigator.clipboard.writeText(data.resilientCode);
        setCopiedFix(true);
        setTimeout(() => setCopiedFix(false), 2000);
    };

    const quickQuestions = view.ctx?.tutor_needed
        ? ['Why did my code fail?', 'Explain the fix line by line', 'How do I verify the fix?']
        : view.ctx?.handled_correctly
            ? ['Why did this pass?', 'What should I test next?']
            : ['Why did this test fail?', 'How does the circuit breaker pattern work?'];

    const outcomeColor = view.ctx?.tutor_needed ? '#ef4444' : (view.ctx?.handled_correctly ? '#10b981' : '#f59e0b');

    // 4 Distinct Dynamic Explanation Blocks:
    // 1. Reason Block
    // 2. Fix Block
    // 3. Fragile / Error Code Block
    // 4. Resilient Fix Code Block
    const hasReasonData = !!(data.rootCause || data.injectedDesc || data.impact || data.locationFile || (data.traceLines && data.traceLines.length > 0));
    const hasFixData = !!(data.fixAction || data.fixExplanation || (data.fixNotes && data.fixNotes.length > 0) || (data.suggestedActions && data.suggestedActions.length > 0) || (data.fixImports && data.fixImports.length > 0));
    const hasErrorCode = !!data.fragileCode;
    const hasFixCode = !!(data.resilientCode || data.patternTitle || data.patternDesc);

    return (
        <div className="chaos-tutor-view">
            <style>{`

                .chaos-tutor-view {
                    padding: 32px;
                    color: var(--text-main, #f3f4f6);
                    font-family: var(--font-sans, 'Inter', system-ui, -apple-system, sans-serif);
                    box-sizing: border-box;
                    width: 100%;
                    max-width: 1600px;
                    margin: 0 auto;
                    position: relative;
                    z-index: 1;
                }

                .chaos-tutor-view * {
                    box-sizing: border-box;
                }

                .chaos-workspace {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                    gap: 20px;
                    align-items: start;
                    width: 100%;
                    max-width: 100%;
                }

                @media (max-width: 1100px) {
                    .chaos-workspace {
                        grid-template-columns: minmax(0, 1fr);
                    }
                }

                /* ================= SHARED GLASS PANEL ================= */
                .chaos-panel {
                    background: rgba(11, 14, 22, 0.65);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 12px;
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.6), 0 0 20px rgba(99, 102, 241, 0.1);
                    display: flex;
                    flex-direction: column;
                    position: relative;
                    overflow: hidden;
                    transition: border-color 0.25s ease, box-shadow 0.25s ease;
                }

                .chaos-chatPanel {
                    height: auto;
                    min-height: calc(100vh - 135px);
                    display: flex;
                    flex-direction: column;
                }

                .chaos-explanationPanel {
                    min-height: 520px;
                }

                .chaos-panel:hover {
                    border-color: rgba(99, 102, 241, 0.35);
                    box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.6), 0 0 20px rgba(99, 102, 241, 0.18);
                }

                /* ================= LEFT: CHAT PANEL ================= */
                .chaos-panelHeader {
                    min-height: 74px;
                    height: auto;
                    padding: 16px 20px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    background: rgba(14, 18, 28, 0.6);
                    flex-shrink: 0;
                    gap: 12px;
                    flex-wrap: wrap;
                }

                .chaos-panelTitle {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }

                .chaos-titleIcon {
                    width: 40px;
                    height: 40px;
                    background: rgba(99, 102, 241, 0.16);
                    border: 1px solid rgba(129, 140, 248, 0.3);
                    border-radius: 11px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: #a5b4fc;
                    flex-shrink: 0;
                }

                .chaos-panelTitle h2 {
                    font-size: 15px;
                    font-weight: 750;
                    color: #f8fafc;
                    margin: 0;
                    letter-spacing: -0.2px;
                }

                .chaos-panelTitle p {
                    color: #94a3b8;
                    font-size: 11px;
                    margin: 3px 0 0 0;
                }

                .chaos-clearButton {
                    background: rgba(239, 68, 68, 0.08);
                    color: #f87171;
                    border: 1px solid rgba(239, 68, 68, 0.25);
                    border-radius: 8px;
                    padding: 7px 12px;
                    font-size: 11px;
                    font-weight: 600;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    transition: all 0.2s ease;
                }

                .chaos-clearButton:hover {
                    background: rgba(239, 68, 68, 0.18);
                    border-color: rgba(239, 68, 68, 0.45);
                    color: #fca5a5;
                }

                .chaos-chatBody {
                    flex: 1 1 auto;
                    height: auto;
                    padding: 18px 20px 8px 20px;
                    position: relative;
                    overflow-y: auto;
                    min-height: 0;
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }

                .chaos-userMessage {
                    display: flex;
                    flex-direction: column;
                    align-items: flex-end;
                    margin-bottom: 0;
                }

                .chaos-userMessage small,
                .chaos-messageTop small {
                    color: #64748b;
                    font-size: 10px;
                    margin-bottom: 4px;
                }

                .chaos-userBubble {
                    background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
                    padding: 12px 16px;
                    border-radius: 14px 14px 4px 14px;
                    font-size: 12px;
                    line-height: 1.6;
                    max-width: 80%;
                    color: #ffffff;
                    word-break: break-word;
                    border: 1px solid rgba(199, 210, 254, 0.2);
                    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.25);
                }

                .chaos-aiMessage {
                    display: flex;
                    gap: 10px;
                    margin-bottom: 0;
                    align-items: flex-start;
                }

                .chaos-smallRobot {
                    width: 32px;
                    height: 32px;
                    flex-shrink: 0;
                    border-radius: 9px;
                    background: rgba(99, 102, 241, 0.16);
                    border: 1px solid rgba(129, 140, 248, 0.28);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: #a5b4fc;
                }

                .chaos-loadingBox,
                .chaos-answerBox {
                    background: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 12px;
                    padding: 14px 16px;
                    max-width: 84%;
                    backdrop-filter: blur(8px);
                }

                .chaos-messageTop {
                    display: flex;
                    justify-content: space-between;
                    gap: 24px;
                    margin-bottom: 8px;
                }

                .chaos-messageTop b {
                    font-size: 11px;
                    color: #a5b4fc;
                    font-weight: 700;
                    letter-spacing: 0.2px;
                }

                .chaos-loadingBox p,
                .chaos-answerBox > p {
                    color: #cbd5e1;
                    font-size: 12px;
                    line-height: 1.6;
                    margin: 0;
                    word-break: break-word;
                    white-space: pre-wrap;
                }

                .chaos-dots {
                    display: flex;
                    gap: 6px;
                    margin-top: 10px;
                }

                .chaos-dots i {
                    width: 6px;
                    height: 6px;
                    border-radius: 50%;
                    background: #818cf8;
                    animation: chaos-pulse 1s infinite;
                    display: inline-block;
                }

                .chaos-dots i:nth-child(2) { animation-delay: .15s; }
                .chaos-dots i:nth-child(3) { animation-delay: .3s; }
                .chaos-dots i:nth-child(4) { animation-delay: .45s; }

                @keyframes chaos-pulse {
                    0%, 100% { opacity: .25; transform: scale(0.9); }
                    50% { opacity: 1; transform: scale(1.1); }
                }

                .chaos-chatInput {
                    position: relative;
                    margin: 8px 18px 18px 18px;
                    height: 52px;
                    border: 1px solid rgba(129, 140, 248, 0.22);
                    border-radius: 12px;
                    background: rgba(11, 14, 22, 0.92);
                    backdrop-filter: blur(12px);
                    display: flex;
                    align-items: center;
                    padding: 6px 8px 6px 14px;
                    flex-shrink: 0;
                    z-index: 5;
                    transition: border-color 0.2s ease, box-shadow 0.2s ease;
                }

                .chaos-chatInput:focus-within {
                    border-color: rgba(99, 102, 241, 0.5);
                    box-shadow: 0 0 16px rgba(99, 102, 241, 0.2);
                }

                .chaos-chatInput input,
                .chaos-chatInput input[type="text"],
                .chaos-chatInput input[type="text"]:hover,
                .chaos-chatInput input[type="text"]:focus,
                .chaos-chatInput input[type="text"]:focus-visible,
                .chaos-chatInput input[type="text"]:active {
                    flex: 1;
                    background: transparent !important;
                    border: none !important;
                    outline: none !important;
                    box-shadow: none !important;
                    color: #f1f5f9 !important;
                    font-size: 12px;
                    font-family: inherit;
                    padding: 0 4px !important;
                    -webkit-appearance: none !important;
                    appearance: none !important;
                }

                .chaos-chatInput input::placeholder {
                    color: #64748b;
                }

                .chaos-chatInput button {
                    width: 38px;
                    height: 38px;
                    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
                    color: white;
                    border: 1px solid rgba(199, 210, 254, 0.2);
                    border-radius: 8px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: transform 0.15s ease, filter 0.15s ease;
                    box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
                }

                .chaos-chatInput button:hover:not(:disabled) {
                    filter: brightness(1.1);
                    transform: scale(1.03);
                }

                .chaos-chatInput button:disabled {
                    opacity: 0.35;
                    cursor: not-allowed;
                    box-shadow: none;
                }

                /* ================= RIGHT: EXPLANATION PANEL ================= */
                .chaos-explanationHeader {
                    padding: 16px 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
                    min-height: 74px;
                    height: auto;
                    background: rgba(14, 18, 28, 0.6);
                    flex-shrink: 0;
                    gap: 12px;
                    flex-wrap: wrap;
                }

                .chaos-explanationHeader h2 {
                    font-size: 15px;
                    font-weight: 750;
                    color: #f8fafc;
                    margin: 0;
                    letter-spacing: -0.2px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                .chaos-generated {
                    color: #34d399;
                    background: rgba(16, 185, 129, 0.12);
                    border: 1px solid rgba(16, 185, 129, 0.32);
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 0.3px;
                }

                .chaos-failureInfo {
                    display: flex;
                    gap: 12px;
                    padding: 16px 22px 10px;
                    flex-shrink: 0;
                }

                .chaos-failureInfo div {
                    flex: 1;
                    background: rgba(255, 255, 255, 0.03);
                    border-radius: 9px;
                    padding: 10px 14px;
                    color: #94a3b8;
                    font-size: 11px;
                    border: 1px solid rgba(255, 255, 255, 0.07);
                }

                .chaos-failureInfo b {
                    color: #f87171;
                    margin-left: 6px;
                    font-weight: 700;
                }

                .chaos-explanationContent { min-width: 0; max-width: 100%; box-sizing: border-box; overflow-x: hidden; }
                .chaos-explanationContent > * { min-width: 0; max-width: 100%; box-sizing: border-box; }
                .chaos-explanationContent p, .chaos-explanationContent li, .chaos-explanationContent span, .chaos-explanationContent code, .chaos-explanationContent div { overflow-wrap: anywhere; word-break: break-word; }
                .chaos-explanationContent pre { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; max-width: 100%; max-height: 260px; overflow: auto; box-sizing: border-box; }
                .chaos-codeDiff { min-width: 0; }
                .chaos-diffPane { min-width: 0; }

                .chaos-explanationContent {
                    padding: 6px 22px 22px;
                    overflow-y: auto;
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    gap: 14px;
                }

                .chaos-reasonCard {
                    background: rgba(239, 68, 68, 0.06);
                    border: 1px solid rgba(239, 68, 68, 0.25);
                    border-radius: 12px;
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    padding: 16px 18px;
                    transition: border-color 0.25s ease, box-shadow 0.25s ease;
                }

                .chaos-reasonCard:hover {
                    border-color: rgba(239, 68, 68, 0.45);
                    box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.5), 0 0 16px rgba(239, 68, 68, 0.2);
                }

                .chaos-reasonCard h3 {
                    color: #f87171;
                    font-size: 12px;
                    margin: 0 0 8px 0;
                    font-weight: 700;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }

                .chaos-reasonCard p,
                .chaos-reasonCard li {
                    color: #cbd5e1;
                    font-size: 12px;
                    line-height: 1.6;
                    margin: 0;
                }

                .chaos-reasonCard ul {
                    padding-left: 18px;
                    margin-top: 8px;
                }

                .chaos-fixCard {
                    background: rgba(245, 158, 11, 0.06);
                    border: 1px solid rgba(245, 158, 11, 0.25);
                    border-radius: 12px;
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    padding: 16px 18px;
                    transition: border-color 0.25s ease, box-shadow 0.25s ease;
                }

                .chaos-fixCard:hover {
                    border-color: rgba(245, 158, 11, 0.45);
                    box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.5), 0 0 16px rgba(245, 158, 11, 0.2);
                }

                .chaos-fixCard h3 {
                    color: #fbbf24;
                    font-size: 12px;
                    margin: 0 0 8px 0;
                    font-weight: 700;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }

                .chaos-fixCard p {
                    color: #cbd5e1;
                    font-size: 12px;
                    margin: 6px 0;
                    line-height: 1.5;
                }

                /* ================= BLOCK 3: ERROR CODE CARD ================= */
                .chaos-errorCodeCard {
                    background: rgba(11, 14, 22, 0.65);
                    border: 1px solid rgba(239, 68, 68, 0.28);
                    border-radius: 12px;
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    overflow: hidden;
                    min-width: 0;
                    max-width: 100%;
                    transition: border-color 0.25s ease, box-shadow 0.25s ease;
                }

                .chaos-errorCodeCard:hover {
                    border-color: rgba(239, 68, 68, 0.5);
                    box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.5), 0 0 16px rgba(239, 68, 68, 0.2);
                }

                .chaos-errorCodeHeader {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 10px 14px;
                    background: rgba(239, 68, 68, 0.1);
                    border-bottom: 1px solid rgba(239, 68, 68, 0.2);
                    gap: 10px;
                    flex-wrap: wrap;
                    min-width: 0;
                }

                .chaos-errorCodeTitle {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 12px;
                    font-weight: 700;
                    color: #f87171;
                    min-width: 0;
                }

                .chaos-errorCodeFile {
                    font-size: 11px;
                    color: #fca5a5;
                    background: rgba(239, 68, 68, 0.15);
                    border: 1px solid rgba(239, 68, 68, 0.3);
                    padding: 2px 8px;
                    border-radius: 4px;
                    font-family: var(--font-mono, monospace);
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    max-width: min(280px, 100%);
                    min-width: 0;
                }

                .chaos-errorCodeBody {
                    padding: 12px 14px;
                    margin: 0;
                    font-family: var(--font-mono, 'JetBrains Mono', monospace);
                    font-size: 11.5px;
                    line-height: 1.6;
                    color: #fca5a5;
                    background: rgba(10, 12, 18, 0.85);
                    overflow-x: auto;
                    white-space: pre-wrap;
                    word-break: break-all;
                    max-height: 380px;
                    max-width: 100%;
                }

                /* ================= BLOCK 4: FIX CODE CARD ================= */
                .chaos-fixCodeCard {
                    background: rgba(11, 14, 22, 0.65);
                    border: 1px solid rgba(16, 185, 129, 0.28);
                    border-radius: 12px;
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    overflow: hidden;
                    min-width: 0;
                    max-width: 100%;
                    transition: border-color 0.25s ease, box-shadow 0.25s ease;
                }

                .chaos-fixCodeCard:hover {
                    border-color: rgba(16, 185, 129, 0.5);
                    box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.5), 0 0 16px rgba(16, 185, 129, 0.2);
                }

                .chaos-fixCodeHeader {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 10px 14px;
                    background: rgba(16, 185, 129, 0.1);
                    border-bottom: 1px solid rgba(16, 185, 129, 0.2);
                    gap: 10px;
                    flex-wrap: wrap;
                    min-width: 0;
                }

                .chaos-fixCodeTitle {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 12px;
                    font-weight: 700;
                    color: #34d399;
                    min-width: 0;
                }

                .chaos-fixCodeFile {
                    font-size: 11px;
                    color: #6ee7b7;
                    background: rgba(16, 185, 129, 0.15);
                    border: 1px solid rgba(16, 185, 129, 0.3);
                    padding: 2px 8px;
                    border-radius: 4px;
                    font-family: var(--font-mono, monospace);
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    max-width: min(280px, 100%);
                    min-width: 0;
                }

                .chaos-fixCodeDesc {
                    padding: 8px 14px;
                    font-size: 11.5px;
                    color: #cbd5e1;
                    background: rgba(16, 185, 129, 0.04);
                    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                    line-height: 1.5;
                    word-break: break-word;
                    overflow-wrap: anywhere;
                }

                .chaos-fixCodeBody {
                    padding: 12px 14px;
                    margin: 0;
                    font-family: var(--font-mono, 'JetBrains Mono', monospace);
                    font-size: 11.5px;
                    line-height: 1.6;
                    color: #6ee7b7;
                    background: rgba(10, 12, 18, 0.85);
                    overflow-x: auto;
                    white-space: pre-wrap;
                    word-break: break-all;
                    max-height: 380px;
                    max-width: 100%;
                }

                .chaos-copyCode {
                    background: rgba(255, 255, 255, 0.06);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    color: #cbd5e1;
                    border-radius: 6px;
                    padding: 5px 9px;
                    cursor: pointer;
                    font-size: 11px;
                    display: flex;
                    align-items: center;
                    gap: 5px;
                    transition: all 0.15s ease;
                    position: static;
                }

                .chaos-copyCode:hover {
                    background: rgba(99, 102, 241, 0.2);
                    border-color: rgba(99, 102, 241, 0.4);
                    color: #ffffff;
                }

            

                .chaos-topBar {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 20px;
                    flex-wrap: wrap;
                    width: 100%;
                    background: rgba(11, 14, 22, 0.65);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 12px;
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    transition: border-color 0.25s ease, box-shadow 0.25s ease;
                }

                .chaos-topBar:hover {
                    border-color: rgba(99, 102, 241, 0.35);
                    box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.6), 0 0 20px rgba(99, 102, 241, 0.15);
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

            `}</style>

            {/* LIVE SPINNER NOTIFICATION BANNER: Tells which project is running & the injected error */}
            {runningNow && (
                <SpotlightCard
                    spotlightColor="rgba(99, 102, 241, 0.28)"
                    className="chaos-runningBanner"
                    style={{ padding: '14px 20px', marginBottom: '18px' }}
                >
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
                </SpotlightCard>
            )}

            {/* Top Project & Run Status Bar */}
            <SpotlightCard
                spotlightColor="rgba(99, 102, 241, 0.2)"
                className="chaos-topBar"
                style={{ padding: '12px 18px', marginBottom: '20px' }}
            >
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
            </SpotlightCard>

            {/* Loading Indicator */}
            {view.loading && !view.ctx && (
                <div className="chaos-loadingNotice">
                    <Loader2 size={15} className="spin" color="#818cf8" />
                    <span>Loading test diagnosis for <strong>{runningProjectName}</strong> ({runningInjectedError || 'Experiment'})…</span>
                </div>
            )}

            {/* Empty State when first test is running on a project */}
            {projectId && !activeRunId && runningNow && (
                <SpotlightCard
                    spotlightColor="rgba(99, 102, 241, 0.22)"
                    style={{ padding: 36, textAlign: 'center', margin: '0 auto 24px', maxWidth: 640 }}
                >
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
                </SpotlightCard>
            )}

            {/* Main 2-Column Equal Workspace: Chat Left, AI Tutor Right */}
            <div className="chaos-workspace">

                {/* LEFT: AI TUTOR CHAT PANEL */}
                <SpotlightCard
                    spotlightColor="rgba(99, 102, 241, 0.22)"
                    className="chaos-panel chaos-chatPanel"
                    style={{
                        padding: 0,
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
                </SpotlightCard>

                {/* RIGHT: AI TUTOR EXPLANATION PANEL */}
                <SpotlightCard
                    ref={explanationRef}
                    spotlightColor="rgba(99, 102, 241, 0.22)"
                    className="chaos-panel chaos-explanationPanel"
                    style={{ padding: 0 }}
                >
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
                            <SpotlightCard
                                spotlightColor="rgba(239, 68, 68, 0.2)"
                                className="chaos-reasonCard"
                                style={{ padding: '16px 18px' }}
                            >
                                <h3>{view.ctx?.handled_correctly ? '✅ What was tested' : '⚠️ Reason'}</h3>
                                {data.rootCause && (
                                    <p style={{ marginBottom: '8px', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                        <strong style={{ color: '#f3f4f6' }}>{view.ctx?.handled_correctly ? 'What happened:' : 'Why it failed:'}</strong> {data.rootCause}
                                    </p>
                                )}
                                {data.injectedDesc && (
                                    <p style={{ marginBottom: '8px', color: '#cbd5e1', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                        {data.injectedDesc}
                                    </p>
                                )}
                                {data.impact && (
                                    <div style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: 8, padding: '8px 12px', marginBottom: '10px', display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
                                        <span style={{ color: '#f59e0b', fontSize: 13, flexShrink: 0 }}>⚠</span>
                                        <span style={{ fontSize: 12, color: '#f59e0b', fontWeight: 500, minWidth: 0, wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                            <strong>{view.ctx?.handled_correctly ? 'Result:' : 'What this means for users:'}</strong> {data.impact}
                                        </span>
                                    </div>
                                )}
                                {data.locationFile && (
                                    <p style={{ fontSize: 12, color: '#a5b4fc', marginBottom: '8px', wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                                        Where in the code: <code style={{ background: 'rgba(255,255,255,0.08)', padding: '2px 6px', borderRadius: 4, fontFamily: 'monospace', wordBreak: 'break-all', overflowWrap: 'anywhere', display: 'inline-block', maxWidth: '100%' }}>{data.locationFile}{data.locationLine ? `:${data.locationLine}` : ''}</code>
                                    </p>
                                )}
                                {data.traceLines && data.traceLines.length > 0 && (
                                    <div style={{ marginTop: '8px', background: 'rgba(4,6,12,0.6)', borderRadius: 8, padding: '10px 14px', overflowX: 'auto', maxWidth: '100%' }}>
                                        <div style={{ fontSize: 10, fontWeight: 700, color: '#64748b', letterSpacing: '0.6px', textTransform: 'uppercase', marginBottom: 6 }}>{view.ctx?.handled_correctly ? 'Technical details (for reference)' : 'Technical details: what the program printed'}</div>
                                        {data.traceLines.slice(0, 6).map((line, idx) => (
                                             <div key={idx} style={{ fontFamily: 'monospace', fontSize: 11, lineHeight: 1.6, color: idx === 0 ? '#f87171' : '#94a3b8', whiteSpace: 'pre-wrap', wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                                                {line}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </SpotlightCard>
                        )}

                        {/* 2. DYNAMIC FIX BLOCK: Appears ONLY if real recommended fix data exists for this specific error */}
                        {hasFixData && (
                            <SpotlightCard
                                spotlightColor="rgba(245, 158, 11, 0.2)"
                                className="chaos-fixCard"
                                style={{ padding: '16px 18px' }}
                            >
                                <h3>🛠 Fix</h3>
                                {data.fixAction && (
                                    <p style={{ color: '#e2e8f0', fontWeight: 500, marginBottom: '8px', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                        ✓ {data.fixAction}
                                    </p>
                                )}
                                {data.fixExplanation && (
                                    <p style={{ color: '#cbd5e1', fontSize: 12, lineHeight: 1.6, marginBottom: '8px', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                        {data.fixExplanation}
                                    </p>
                                )}
                                {data.fixNotes && data.fixNotes.length > 0 && (
                                    <ul style={{ margin: '6px 0 10px', paddingLeft: 18, color: '#cbd5e1', fontSize: 12, lineHeight: 1.6 }}>
                                        {data.fixNotes.map((note, idx) => (
                                            <li key={idx} style={{ marginBottom: 4, wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{note}</li>
                                        ))}
                                    </ul>
                                )}
                                {data.suggestedActions && data.suggestedActions.length > 0 && (
                                    <div style={{ marginTop: 8 }}>
                                        {data.suggestedActions.map((act, idx) => (
                                            <p key={idx} style={{ color: '#34d399', fontSize: 12, marginBottom: 4, wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                                ✓ {act}
                                            </p>
                                        ))}
                                    </div>
                                )}
                                {data.fixImports && data.fixImports.length > 0 && (
                                    <div style={{ marginTop: 10, background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.22)', borderRadius: 8, padding: '8px 12px', minWidth: 0, maxWidth: '100%' }}>
                                        <div style={{ fontSize: 10, fontWeight: 700, color: '#a5b4fc', textTransform: 'uppercase', marginBottom: 4 }}>Required Imports / Extras</div>
                                        <pre style={{ margin: 0, fontSize: 11, fontFamily: 'monospace', color: '#c7d2fe', whiteSpace: 'pre-wrap', wordBreak: 'break-all', overflowX: 'auto', maxWidth: '100%' }}>{data.fixImports.join('\n')}</pre>
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
                            </SpotlightCard>
                        )}

                        {/* 3. DYNAMIC ERROR CODE BLOCK: Dedicated card for observed vulnerable/error code */}
                        {hasErrorCode && (
                            <SpotlightCard
                                spotlightColor="rgba(239, 68, 68, 0.18)"
                                className="chaos-errorCodeCard"
                                style={{ padding: 0 }}
                            >
                                <div className="chaos-errorCodeHeader">
                                    <div className="chaos-errorCodeTitle">
                                        <AlertTriangle size={15} color="#f87171" />
                                        <span>Fragile / Error Code</span>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                        {data.fragileFile && (
                                            <span className="chaos-errorCodeFile" title={data.fragileFile}>
                                                {data.fragileFile}
                                            </span>
                                        )}
                                        <button
                                            className="chaos-copyCode"
                                            onClick={copyErrorCode}
                                            title="Copy fragile error code"
                                        >
                                            {copiedError ? <><Check size={12} color="#f87171" /> Copied</> : <><Copy size={12} /> Copy Code</>}
                                        </button>
                                    </div>
                                </div>
                                <pre className="chaos-errorCodeBody">{data.fragileCode}</pre>
                            </SpotlightCard>
                        )}

                        {/* 4. DYNAMIC FIX CODE BLOCK: Dedicated card for proposed resilient code */}
                        {hasFixCode && (
                            <SpotlightCard
                                spotlightColor="rgba(16, 185, 129, 0.2)"
                                className="chaos-fixCodeCard"
                                style={{ padding: 0 }}
                            >
                                <div className="chaos-fixCodeHeader">
                                    <div className="chaos-fixCodeTitle">
                                        <ShieldCheck size={16} color="#34d399" />
                                        <span>Resilient Fix Code</span>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                        {(data.patternTitle || data.resilientFile) && (
                                            <span className="chaos-fixCodeFile" title={data.patternTitle || data.resilientFile}>
                                                {data.patternTitle || data.resilientFile}
                                            </span>
                                        )}
                                        {data.resilientCode && (
                                            <button
                                                className="chaos-copyCode"
                                                onClick={copyFixCode}
                                                title="Copy resilient fix code"
                                            >
                                                {copiedFix ? <><Check size={12} color="#34d399" /> Copied</> : <><Copy size={12} /> Copy Code</>}
                                            </button>
                                        )}
                                    </div>
                                </div>
                                <div className="chaos-fixCodeDesc">
                                    {data.patternDesc}
                                </div>
                                {data.resilientCode && (
                                    <pre className="chaos-fixCodeBody">{data.resilientCode}</pre>
                                )}
                            </SpotlightCard>
                        )}

                        {/* CASE: Project handled the fault correctly (tutor not needed) */}
                        {view.ctx?.handled_correctly && (
                            <SpotlightCard
                                spotlightColor="rgba(16, 185, 129, 0.2)"
                                className="chaos-reasonCard"
                                style={{
                                    padding: '16px 18px',
                                    borderColor: 'rgba(16,185,129,0.35)',
                                    background: 'rgba(16,185,129,0.06)'
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                                    <ShieldCheck size={20} color="#10b981" />
                                    <span style={{ fontSize: 16, fontWeight: 700, color: '#34d399', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>Passed: handled safely, no fix needed</span>
                                </div>
                                <p style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.6, margin: 0, wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                    “{runningProjectName}” handled this test the way a strong service should. Nothing went wrong, so there is nothing to fix.
                                </p>
                                {data.fragileCode && (
                                    <div style={{ marginTop: 12 }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: '#34d399', marginBottom: 6 }}>Code that handled it safely ({data.fragileFile || 'project'}):</div>
                                        <pre style={{ margin: 0, padding: 12, borderRadius: 8, background: 'rgba(4,6,12,0.6)', border: '1px solid rgba(16,185,129,0.25)', color: '#a7f3d0', fontSize: 11.5, fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all', overflowX: 'auto', maxWidth: '100%' }}>{data.fragileCode}</pre>
                                    </div>
                                )}
                                <div style={{ marginTop: 14 }}>
                                    <button className="chaos-actionBtn" onClick={() => setCurrentView?.('chaos-lab')}>
                                        <Zap size={13} /> Run another test in Chaos Lab
                                    </button>
                                </div>
                            </SpotlightCard>
                        )}

                        {/* EMPTY STATE: Neither reason, fix, error code, fix code, nor handled */}
                        {!hasReasonData && !hasFixData && !hasErrorCode && !hasFixCode && !view.ctx?.handled_correctly && !runningNow && (
                            <div style={{ textAlign: 'center', padding: '40px 20px', color: '#94a3b8', fontSize: 13 }}>
                                <p style={{ marginBottom: 12 }}>No experiment diagnosis selected or available yet.</p>
                                <button className="chaos-actionBtn" onClick={() => setCurrentView?.('chaos-lab')}>
                                    <Zap size={13} /> Go to Chaos Lab
                                </button>
                            </div>
                        )}
                    </div>
                </SpotlightCard>

            </div>
        </div>
    );
}
