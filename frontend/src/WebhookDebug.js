import React, { useState, useMemo, useEffect, useCallback } from 'react';
import './WebhookDebug.css';

const defaultPayload = () => ({
  attachments: [],
  avatar_url: null,
  created_at: Math.floor(Date.now()/1000),
  group_id: '109174633', // PreProd
  id: crypto.randomUUID(),
  name: 'Bertrand Russell',
  sender_id: '12345678',
  sender_type: 'user',
  source_guid: crypto.randomUUID(),
  system: false,
  text: 'Responding POV ETA 45 min',
  user_id: '12345678',
});

function pretty(obj) {
  try { return JSON.stringify(obj, null, 2); } catch { return String(obj); }
}

export default function WebhookDebug() {
  const [payload, setPayload] = useState(defaultPayload());
  const [apiKey, setApiKey] = useState('');
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [responders, setResponders] = useState(null);
  const [user, setUser] = useState(null);
  const [authError, setAuthError] = useState(null);
  const [copied, setCopied] = useState(null); // which block copied

  const base = useMemo(() => {
    const host = typeof window!== 'undefined' ? window.location.host : '';
    return host.endsWith(':3100') ? 'http://localhost:8000' : '';
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(`${base}/api/user`, { headers: { 'Accept': 'application/json' } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (cancelled) return;
        setUser(j);
        if (!j.authenticated) {
          setAuthError('You must be signed in to access this page.');
        } else if (!j.is_admin) {
          setAuthError('Access denied: admin only.');
        }
      } catch (e) {
        if (!cancelled) setAuthError('Unable to verify sign-in.');
      }
    };
    load();
    return () => { cancelled = true; };
  }, [base]);

  const jsonText = useMemo(() => pretty(payload), [payload]);

  const updateField = (k, v) => setPayload(p => ({ ...p, [k]: v }));

  const copy = useCallback(async (text, key) => {
    try {
      await navigator.clipboard.writeText(typeof text === 'string' ? text : pretty(text));
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {}
  }, []);

  const postWebhook = async () => {
    setSending(true); setError(null); setResult(null);
    try {
      // Backend webhook expects { name, text, created_at, group_id }
      const body = {
        name: payload.name,
        text: payload.text,
        created_at: payload.created_at,
        group_id: payload.group_id,
      };
  const url = `${base}/webhook?debug=true` + (apiKey ? `&api_key=${encodeURIComponent(apiKey)}` : '');
      const r = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const text = await r.text();
      let data = null;
      try { data = JSON.parse(text); } catch { data = { raw: text }; }
      if (!r.ok) throw new Error(data?.detail || `HTTP ${r.status}`);
      setResult(data);

      // fetch responders snapshot
      try {
  const rr = await fetch(`${base}/api/responders`, { headers: { 'Accept': 'application/json' } });
        if (rr.ok) setResponders(await rr.json());
      } catch {}
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSending(false);
    }
  };

  const now = () => updateField('created_at', Math.floor(Date.now()/1000));
  const reset = () => { setPayload(defaultPayload()); setResult(null); setError(null); };

  return (
    <div className="debug-wrap">
      <div className="page-header">
        <div className="title">Webhook Debugger</div>
        <div className="subtitle">Post test messages to <code className="mono">/webhook?debug=true</code> and inspect prompts, parsing, and storage.</div>
      </div>
      {authError && (
        <div className="alert error" role="alert">{authError}</div>
      )}
      {(!user || !user.is_admin) && (
        <p className="helper-text">You must be an admin to use this page.</p>
      )}

      <div className="section-grid">
        <div className="panel">
          {user?.is_admin ? (
            <>
              <div className="panel-title">Compose Test Message</div>
              <div className="form-grid">
                <label className="form-field">
                  <span className="lbl">Name</span>
                  <input className="input" value={payload.name} onChange={e=>updateField('name', e.target.value)} />
                </label>
                <label className="form-field">
                  <span className="lbl">Group ID</span>
                  <input className="input" value={payload.group_id} onChange={e=>updateField('group_id', e.target.value)} />
                </label>
                <label className="form-field span-2">
                  <span className="lbl">Message</span>
                  <textarea className="input" rows={3} value={payload.text} onChange={e=>updateField('text', e.target.value)} />
                </label>
                <label className="form-field">
                  <span className="lbl">Created At (unix seconds)</span>
                  <div className="row">
                    <input className="input" type="number" value={payload.created_at} onChange={e=>updateField('created_at', Number(e.target.value||0))} />
                    <button className="btn" onClick={now}>Now</button>
                  </div>
                </label>
                <label className="form-field">
                  <span className="lbl">API Key (optional)</span>
                  <input className="input" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="if required" />
                </label>
              </div>
              <div className="actions-row">
                <button className="btn primary" onClick={postWebhook} disabled={sending}>{sending? 'Sending…':'Post to /webhook'}</button>
                <button className="btn" onClick={reset}>Reset</button>
              </div>

              <div className="code-card">
                <div className="code-card-head">
                  <div className="code-title">Full example payload</div>
                  <button className="btn sub" onClick={()=>copy(jsonText,'example')}>{copied==='example'?'Copied':'Copy'}</button>
                </div>
                <pre className="code-terminal" aria-label="example-json">{jsonText}</pre>
              </div>
            </>
          ) : (
            <div className="helper-text">Sign in as an admin to use the debugger.</div>
          )}
        </div>

        <div className="panel">
          <div className="panel-title">Result</div>
          {error && <div className="alert error">{error}</div>}
          {user?.is_admin && result && (
            <div className="result-stack">
              <details open className="card-details">
                <summary>Inputs</summary>
                <div className="code-card tight">
                  <div className="code-card-head">
                    <div className="code-title">Request Inputs</div>
                    <button className="btn sub" onClick={()=>copy(result.inputs,'inputs')}>{copied==='inputs'?'Copied':'Copy'}</button>
                  </div>
                  <pre className="code-terminal">{pretty(result.inputs)}</pre>
                </div>
              </details>
              <details open className="card-details">
                <summary>Parsed</summary>
                <div className="code-card tight">
                  <div className="code-card-head">
                    <div className="code-title">Parsed Output</div>
                    <button className="btn sub" onClick={()=>copy(result.parsed,'parsed')}>{copied==='parsed'?'Copied':'Copy'}</button>
                  </div>
                  <pre className="code-terminal">{pretty(result.parsed)}</pre>
                </div>
              </details>
              {result.parsed?.llm_debug && (
                <details className="card-details">
                  <summary>LLM Prompt</summary>
                  <div className="row-col">
                    <div className="code-card tight">
                      <div className="code-card-head">
                        <div className="code-title">System</div>
                        <button className="btn sub" onClick={()=>copy(result.parsed.llm_debug.sys_prompt,'sys')}>{copied==='sys'?'Copied':'Copy'}</button>
                      </div>
                      <pre className="code-terminal">{result.parsed.llm_debug.sys_prompt}</pre>
                    </div>
                    <div className="code-card tight">
                      <div className="code-card-head">
                        <div className="code-title">User</div>
                        <button className="btn sub" onClick={()=>copy(result.parsed.llm_debug.user_prompt,'user')}>{copied==='user'?'Copied':'Copy'}</button>
                      </div>
                      <pre className="code-terminal">{result.parsed.llm_debug.user_prompt}</pre>
                    </div>
                  </div>
                </details>
              )}
              {result.parsed?.llm_debug?.raw_response && (
                <details className="card-details">
                  <summary>LLM Raw Response</summary>
                  <div className="code-card tight">
                    <div className="code-card-head">
                      <div className="code-title">Raw</div>
                      <button className="btn sub" onClick={()=>copy(result.parsed.llm_debug.raw_response,'raw')}>{copied==='raw'?'Copied':'Copy'}</button>
                    </div>
                    <pre className="code-terminal">{result.parsed.llm_debug.raw_response}</pre>
                  </div>
                </details>
              )}
              <details className="card-details">
                <summary>Stored Message</summary>
                <div className="code-card tight">
                  <div className="code-card-head">
                    <div className="code-title">Database Row</div>
                    <button className="btn sub" onClick={()=>copy(result.stored_message,'stored')}>{copied==='stored'?'Copied':'Copy'}</button>
                  </div>
                  <pre className="code-terminal">{pretty(result.stored_message)}</pre>
                </div>
              </details>
            </div>
          )}
          {user?.is_admin && responders && (
            <div className="result-stack">
              <details className="card-details">
                <summary>Current Responders ({responders.length})</summary>
                <div className="code-card tight">
                  <div className="code-card-head">
                    <div className="code-title">Snapshot</div>
                    <button className="btn sub" onClick={()=>copy(responders,'responders')}>{copied==='responders'?'Copied':'Copy'}</button>
                  </div>
                  <pre className="code-terminal">{pretty(responders)}</pre>
                </div>
              </details>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
