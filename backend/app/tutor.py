from __future__ import annotations
"""
Tutor Engine (spec section 25, P1).

Turns a real detection result + diagnosis into the 8-part explanation the
spec asks for, plus one auto-generated comprehension question with a
lightweight keyword-based answer check. Every field is derived from data
this run actually produced — nothing here is a canned lesson unrelated to
what happened.

Also answers free-form follow-up questions ("Ask the Tutor" chat, and the
"Related Concepts" quick-prompts, which both hit the same endpoint). This
mirrors app/diagnosis.py's two-diagnoser shape exactly: an LLM path
(app/llm_providers.py, same provider rotation/failover, same
ENABLE_LLM_DIAGNOSIS-gated spend safety) that answers the learner's actual
question against the run's real evidence, falling back automatically and
silently to a deterministic evidence summary if the LLM path isn't enabled
or every configured provider/key fails.
"""
import json
import os
import sys
import urllib.request

from app import llm_providers

MAX_TUTOR_INPUT_BYTES = 100 * 1024

_CONCEPT_KEYWORDS = {
    "input validation": ["validate", "validation", "sanitize", "type check", "schema"],
    "request size limiting": ["size limit", "content-length", "max size", "reject large"],
    "fail-fast configuration validation": ["fail fast", "fail-fast", "startup check", "required env", "config validation",
                                           "dependency check", "dependencies", "validate config", "health check"],
    "graceful degradation / clear startup error": ["catch", "handle the error", "clear error", "graceful", "fallback"],
    "error handling": ["catch", "handle the exception", "handle the error", "error handling", "validate"],
    "restart / process supervision": ["restart", "supervisor", "supervision", "process manager", "auto-restart"],
    "fail-fast availability signaling": ["fail fast", "clean refusal", "connection refused", "health check"],
    "timeout handling": ["timeout", "time limit", "deadline"],
    "clean failure visibility": ["clean failure", "visible failure", "connection refused", "no hang"],
    "backpressure / concurrency handling": ["backpressure", "rate limit", "429", "queue", "concurrency"],
}


def explain(experiment: dict, detection_result: dict, diagnosis: dict) -> dict:
    outcome = detection_result["outcome"]
    # TARGET_UNREACHABLE means the service never started: nothing was tested,
    # and the learner has something concrete to fix. It is a problem to act on
    # (setup_issue), not a pass - it used to read "handled the way it should be".
    setup_issue = outcome == "TARGET_UNREACHABLE"
    is_problem = outcome in ("APPLICATION_FAILURE", "CRASHED", "WEAK_HANDLING") or setup_issue

    return {
        "what_happened": diagnosis.get("failure") or
                          f"No failure — {detection_result['reasoning']}",
        "why": diagnosis.get("root_cause") or
               "the fault was handled the way it should be, so there's no defect to explain",
        "where": diagnosis.get("affected_component") or experiment["target"],
        "evidence": diagnosis.get("evidence") or [detection_result["reasoning"]],
        "impact": diagnosis.get("impact") or "no negative impact observed for this fault",
        "prevention": diagnosis.get("recommended_fix") or
                       "no change needed — this already matches the expected behavior",
        "recovery": _recovery_note(experiment, detection_result),
        "concept": diagnosis.get("resilience_pattern") or "graceful degradation",
        "is_problem": is_problem,
        "setup_issue": setup_issue,
        "outcome": outcome,
    }


def _recovery_note(experiment, detection_result):
    if experiment["fault_type"] == "process_kill_recovery":
        result = detection_result["evidence"]
        if result.get("recovered"):
            events = result.get("restart_events") or []
            secs = events[-1]["recovered_after_s"] if events else None
            return (f"a simple restart-on-crash supervisor recovered it"
                    f"{f' in {secs}s' if secs is not None else ''} — the 'restart' "
                    "strategy from spec section 24 works for this service")
        return ("no recovery observed within the bound even with a restart supervisor in "
                "front of it — this needs investigation before relying on auto-restart alone")
    if experiment["fault_type"] == "process_kill":
        return ("this run only observed the crash, not recovery — see the paired "
                "process_kill_recovery experiment for whether a restart supervisor helps")
    return "recovery testing isn't applicable to this fault category"


def generate_question(experiment: dict, detection_result: dict, diagnosis: dict) -> dict:
    outcome = detection_result["outcome"]
    concept = diagnosis.get("resilience_pattern") or "graceful degradation"
    if outcome in ("APPLICATION_FAILURE", "CRASHED"):
        outcome_phrase = {
            "APPLICATION_FAILURE": "an application failure",
            "CRASHED": "a crash",
        }[outcome]
        question = (f"'{experiment['name']}' just caused {outcome_phrase}. "
                     "What's the general name for the kind of fix that would prevent this?")
    elif outcome == "WEAK_HANDLING":
        question = ("The service accepted invalid input without rejecting it. What "
                     "category of defensive code is missing here?")
    elif outcome == "TARGET_UNREACHABLE":
        question = (f"'{experiment['name']}' could not run because the service failed to start, before "
                    "any fault was injected. What kind of check at startup makes a problem like a "
                    "missing dependency or setting obvious immediately instead of failing later?")
        concept = "fail-fast configuration validation"
    elif outcome == "RECOVERED":
        question = "What's the name of the recovery strategy that just brought this service back?"
    else:
        question = f"Why did '{experiment['name']}' pass without exposing a weakness?"
    return {
        "question": question,
        "outcome": outcome,
        "_concept": concept,  # not shown to the user; used by evaluate_answer
    }


def _format_ai_tutor_context(run: dict, diagnosis: dict | None, evidence_text: str, code_context: dict | None) -> tuple[str, str]:
    diagnosis = diagnosis or {}
    code_context = code_context or {}
    fault = (
        code_context.get("fault_label")
        or code_context.get("injected_fault")
        or diagnosis.get("failure")
        or diagnosis.get("root_cause")
        or (run and run.get("fault_type"))
        or "Software Fault"
    )

    ctx_items = []
    if code_context.get("project"):
        ctx_items.append(f"Project: {code_context['project']}")
    if code_context.get("injected_fault"):
        ctx_items.append(f"Injected Fault: {code_context['injected_fault']}")
    if code_context.get("source_file"):
        ctx_items.append(f"Problem Location: {code_context['source_file']}, line {code_context.get('source_line', '?')}")
    if code_context.get("source_snippet"):
        ctx_items.append(f"Problematic Code Snippet:\n{code_context['source_snippet']}")
    if code_context.get("suggested_fix_code"):
        title = code_context.get("suggested_fix_title") or "Recommended Fix"
        ctx_items.append(f"Suggested Fix ({title}):\n{code_context['suggested_fix_code']}")
    if diagnosis.get("root_cause"):
        ctx_items.append(f"Root Cause: {diagnosis['root_cause']}")
    if diagnosis.get("affected_component"):
        ctx_items.append(f"Affected Component: {diagnosis['affected_component']}")
    if diagnosis.get("recommended_fix"):
        ctx_items.append(f"Recommended Fix: {diagnosis['recommended_fix']}")
    if diagnosis.get("resilience_pattern"):
        ctx_items.append(f"Resilience Pattern: {diagnosis['resilience_pattern']}")
    if evidence_text and evidence_text.strip():
        ctx_items.append(f"Execution Evidence Trace:\n{evidence_text}")
    if run and run.get("outcome"):
        ctx_items.append(f"Run Outcome: {run['outcome']}")

    return str(fault), "\n\n".join(ctx_items)


# Text the ai_tutor_backend returns (with HTTP 200) when it has no working AI model.
# These are status messages, not tutoring answers, so they must never reach the student.
_AI_TUTOR_PLACEHOLDERS = (
    "gemini api keys are not configured",
    "i am currently unable to reach the ai model",
)


def _is_placeholder_answer(answer) -> bool:
    text = str(answer or "").strip().lower()
    return (not text) or any(text.startswith(p) for p in _AI_TUTOR_PLACEHOLDERS)


def answer_with_ai_tutor_backend(question: str, run: dict, diagnosis: dict | None, evidence_text: str,
                                 history: list, code_context: dict | None) -> dict | None:
    """Delegate chatbot responses to the dedicated ai_tutor_backend project."""
    fault, context_str = _format_ai_tutor_context(run, diagnosis, evidence_text, code_context)

    # 1. Try ai_tutor_backend HTTP service (port 5000)
    try:
        req_data = json.dumps({
            "question": question,
            "fault": fault,
            "context": context_str,
            "history": history,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:5000/api/chat",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status == 200:
                res_body = json.loads(resp.read().decode("utf-8"))
                if res_body.get("answer") and not _is_placeholder_answer(res_body["answer"]):
                    return {"answer": res_body["answer"], "method": "ai_tutor_backend_http"}
    except Exception:
        pass

    # 2. Try direct import of ai_tutor_backend module
    try:
        candidate_dirs = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ai_tutor_backend")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_tutor_backend")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "ai_tutor_backend")),
            r"C:\Users\pc\Downloads\ai_tutor_backend",
        ]
        ai_tutor_dir = next((d for d in candidate_dirs if os.path.exists(os.path.join(d, "ai_tutor.py"))), None)
        if ai_tutor_dir:
            if ai_tutor_dir not in sys.path:
                sys.path.insert(0, ai_tutor_dir)
            import ai_tutor
            answer = ai_tutor.chat_with_ai(question, fault=fault, context=context_str, history=history)
            if not _is_placeholder_answer(answer):
                return {"answer": answer, "method": "ai_tutor_backend_direct"}
    except Exception as e:
        print(f"[tutor] direct ai_tutor_backend call error: {e}", file=sys.stderr)

    return None


def answer_question(question: str, run: dict, diagnosis: dict | None, evidence_text: str,
                     history: list | None = None, code_context: dict | None = None) -> dict:
    history = history or []
    if llm_providers.diagnosis_enabled():
        try:
            return _llm_answer(question, run, diagnosis, evidence_text, history, code_context)
        except Exception as e:
            print(f"[tutor] LLM answer failed, falling back to rule-based: {e}", file=sys.stderr)
            return _rule_based_answer(question, run, diagnosis, evidence_text, code_context)
    return _rule_based_answer(question, run, diagnosis, evidence_text, code_context)


_FIX_WORDS = ("fix", "solve", "solution", "code", "patch", "change", "how do i", "how to", "correct", "repair")


def _rule_based_answer(question: str, run: dict, diagnosis: dict | None, evidence_text: str,
                       code_context: dict | None = None) -> dict:
    diagnosis = diagnosis or {}
    code_context = code_context or {}
    q = (question or "").lower()
    if code_context.get("handled_correctly"):
        where = f" ({code_context['source_file']}, line {code_context['source_line']})" if code_context.get("source_file") else ""
        return {"answer": (
            f"Good news: {code_context.get('project') or 'your project'} handled \"{code_context.get('fault_label')}\" correctly{where}. "
            f"Injected: {code_context.get('injected_fault')} Nothing needs fixing for this test. "
            "Ask me why it passed, or run another test to look for weak spots."), "method": "rule_based"}
    if code_context.get("source_file") and any(w in q for w in _FIX_WORDS):
        parts = [f"In {code_context.get('project') or 'your project'}, the injected error was: {code_context.get('injected_fault')}",
                 f"It lands on {code_context['source_file']}, line {code_context['source_line']}:",
                 code_context.get("source_snippet") or ""]
        if code_context.get("suggested_fix_code"):
            parts += [f"Suggested change — {code_context.get('suggested_fix_title')}:", code_context["suggested_fix_code"]]
            parts += [f"- {n}" for n in (code_context.get("suggested_fix_notes") or [])]
        else:
            parts.append(f"Recommended fix: {diagnosis.get('recommended_fix') or 'add explicit error handling around this code path'}.")
        return {"answer": "\n".join(p for p in parts if p), "method": "rule_based"}
    where_txt = ""
    if code_context.get("source_file"):
        where_txt = (f"Injected: {code_context.get('injected_fault')} "
                     f"It reaches your code at {code_context['source_file']}, line {code_context['source_line']}. ")
    answer = where_txt + (
        f"Run outcome: {run.get('outcome') or 'unknown'}. "
        f"Root cause: {diagnosis.get('root_cause') or diagnosis.get('failure') or 'not recorded'}. "
        f"Affected component: {diagnosis.get('affected_component') or 'not recorded'}. "
        f"Recommended fix: {diagnosis.get('recommended_fix') or 'review the recorded evidence and add an appropriate resilience control'}. "
        f"Evidence: {evidence_text or 'not recorded'}. "
        f"This is a general summary of the run rather than a tailored answer to "
        f"\"{question.strip()}\" — enable AI diagnosis for answers to specific "
        f"follow-up questions."
    )
    return {"answer": answer, "method": "rule_based"}


def _llm_answer(question: str, run: dict, diagnosis: dict | None, evidence_text: str,
                 history: list, code_context: dict | None = None) -> dict:
    diagnosis = diagnosis or {}
    context = {
        "project_code_context": code_context or {},
        "run_outcome": run.get("outcome"),
        "root_cause": diagnosis.get("root_cause") or diagnosis.get("failure"),
        "affected_component": diagnosis.get("affected_component"),
        "recommended_fix": diagnosis.get("recommended_fix"),
        "resilience_pattern": diagnosis.get("resilience_pattern"),
        "evidence": evidence_text,
    }
    system_prompt = (
        "You are the AI Tutor inside a chaos-engineering learning tool. "
        "You are given the structured facts about ONE experiment run "
        "(its outcome, root cause, affected component, recommended fix, "
        "raw evidence, and the learner's own source lines that the injected error "
        "landed on plus a suggested fix), the prior turns of this conversation if any, "
        "and a new follow-up question a learner is asking. Answer the "
        "learner's actual question directly and conversationally, using "
        "the prior turns to resolve references like 'that' or 'the "
        "second one', and grounded only in the given facts — do not "
        "invent detail the evidence doesn't support. Respond with ONLY a "
        "JSON object with exactly one key, \"answer\", whose value is your "
        "explanation as a plain string. No markdown fences, no other "
        "keys, no text outside the JSON object."
    )
    user_content = json.dumps(
        {"context": context, "conversation_history": history, "question": question},
        default=str,
    )[:MAX_TUTOR_INPUT_BYTES]

    parsed = llm_providers.diagnose_with_llm(system_prompt, user_content)
    answer = parsed.get("answer")
    if not answer or not isinstance(answer, str):
        raise ValueError("LLM tutor response missing a string 'answer' field")
    return {"answer": answer, "method": "llm"}


def evaluate_answer(question: dict, user_answer: str) -> dict:
    concept = question.get("_concept", "")
    keywords = _CONCEPT_KEYWORDS.get(concept, [concept.lower()]) if concept else []
    answer_lower = (user_answer or "").lower()
    hit = any(k in answer_lower for k in keywords) or (concept and concept.lower() in answer_lower)
    return {
        "correct": bool(hit),
        "expected_concept": concept,
        "feedback": (f"Right idea — this is a case for {concept}." if hit else
                     f"Not quite — the concept demonstrated here is {concept}."),
    }
