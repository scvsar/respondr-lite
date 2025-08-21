import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
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
  const [overrideEnabled, setOverrideEnabled] = useState(false);
  const [sysPrompt, setSysPrompt] = useState('');
  const [userPrompt, setUserPrompt] = useState('');
  const [loadingPrompts, setLoadingPrompts] = useState(false);
  const [groups, setGroups] = useState([]);
  const [fullEditEnabled, setFullEditEnabled] = useState(false);
  const [fullPayloadText, setFullPayloadText] = useState(() => JSON.stringify(defaultPayload(), null, 2));
  const [verbosity, setVerbosity] = useState(''); // '', 'low', 'medium', 'high'
  const [reasoning, setReasoning] = useState(''); // '', 'minimal', 'low', 'medium', 'high'
  const [maxTokens, setMaxTokens] = useState(''); // numeric string; empty means default
  const sysRef = useRef(null);
  const userRef = useRef(null);
  const overridesDetailsRef = useRef(null);

  const autoResize = useCallback((el) => {
    if (!el) return;
    
    // Reset height to allow shrink, then expand to content
    el.style.height = 'auto';
    const nextHeight = el.scrollHeight;
    el.style.height = `${nextHeight}px`;
  }, []);

  // Simple resize on input - no debouncing, just immediate resize
  const handleInput = useCallback((el) => {
    requestAnimationFrame(() => autoResize(el));
  }, [autoResize]);

  const base = useMemo(() => {
    const host = typeof window!== 'undefined' ? window.location.host : '';
    // Treat common dev ports as frontend-only, pointing API to localhost:8000
    if (/localhost:(3000|3100|5173)$/i.test(host)) return 'http://localhost:8000';
    return host.endsWith(':3100') ? 'http://localhost:8000' : '';
  }, []);

  const fetchWithFallback = useCallback(async (path, init) => {
    const urls = [];
    urls.push(`${base}${path}`);
    if (!base) urls.push(`http://localhost:8000${path}`);
    let last;
    for (const u of urls) {
      try {
        const r = await fetch(u, init);
        if (r.ok) return r;
        last = r;
      } catch (e) {
        last = e;
      }
    }
    if (last instanceof Response) throw new Error(`HTTP ${last.status}`);
    throw last || new Error('Request failed');
  }, [base]);

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

  useEffect(() => {
    let cancelled = false;
    const loadGroups = async () => {
      try {
    const r = await fetchWithFallback(`/api/config/groups`, { headers: { 'Accept': 'application/json' } });
    if (!r.ok) return; // likely non-admin
        const j = await r.json();
        if (!cancelled) setGroups(j.groups || []);
      } catch {}
    };
    loadGroups();
    return () => { cancelled = true; };
  }, [base, fetchWithFallback]);

  // Load default prompts once on mount so fields are pre-populated (button can be used to reload later)
  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      try {
        const params = new URLSearchParams();
        params.set('text', payload.text || '');
        if (payload.created_at) params.set('created_at', String(payload.created_at));
        const r = await fetchWithFallback(`/api/debug/default-prompts?${params.toString()}`, { headers: { 'Accept': 'application/json' } });
        if (!r.ok) return;
        const j = await r.json();
        if (cancelled) return;
        setSysPrompt(j.sys_prompt || '');
        setUserPrompt(j.user_prompt || '');
        // Do NOT auto-enable overrides; leave control to the user
        // Trigger resize after setting prompts
        setTimeout(() => {
          if (sysRef.current) autoResize(sysRef.current);
          if (userRef.current) autoResize(userRef.current);
        }, 100);
      } catch {}
    };
    init();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When the overrides panel is toggled open, re-measure and expand
  const onOverridesToggle = useCallback(() => {
    if (overridesDetailsRef.current && overridesDetailsRef.current.open) {
      // allow layout settle
      setTimeout(() => {
        if (sysRef.current) autoResize(sysRef.current);
        if (userRef.current) autoResize(userRef.current);
      }, 0);
    }
  }, [autoResize]);

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
      let source = payload;
      if (fullEditEnabled) {
        try {
          source = JSON.parse(fullPayloadText);
        } catch (e) {
          throw new Error('Full payload JSON is invalid');
        }
      }
      const body = {
        name: source.name,
        text: source.text,
        created_at: source.created_at,
        group_id: source.group_id,
      };
      if (overrideEnabled) {
        if (sysPrompt.trim()) body.debug_sys_prompt = sysPrompt;
        if (userPrompt.trim()) body.debug_user_prompt = userPrompt;
  if (verbosity) body.debug_verbosity = verbosity;
  if (reasoning) body.debug_reasoning = reasoning;
        if (String(maxTokens).trim()) {
          const n = Number(maxTokens);
          if (!Number.isNaN(n) && n > 0) body.debug_max_tokens = n;
        }
      }
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
  const loadDefaultPrompts = async () => {
    setLoadingPrompts(true);
    try {
      const params = new URLSearchParams();
      params.set('text', payload.text || '');
      if (payload.created_at) params.set('created_at', String(payload.created_at));
  const r = await fetchWithFallback(`/api/debug/default-prompts?${params.toString()}`, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setSysPrompt(j.sys_prompt || '');
      setUserPrompt(j.user_prompt || '');
      // Manually trigger resize after setting the prompts
      setTimeout(() => {
        if (sysRef.current) autoResize(sysRef.current);
        if (userRef.current) autoResize(userRef.current);
      }, 50);
    } catch (e) {
      setError(`Failed to load default prompts: ${e.message || e}`);
    } finally {
      setLoadingPrompts(false);
    }
  };

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
                  {groups && groups.length > 0 ? (
                    <select className="input" value={payload.group_id} onChange={e=>updateField('group_id', e.target.value)}>
                      {groups.map(g => (
                        <option key={g.group_id} value={g.group_id}>{g.group_id} — {g.team}</option>
                      ))}
                    </select>
                  ) : (
                    <input className="input" value={payload.group_id} onChange={e=>updateField('group_id', e.target.value)} />
                  )}
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
              <details className="card-details" ref={overridesDetailsRef} onToggle={onOverridesToggle}>
                <summary>Prompt Overrides</summary>
                <div className="form-grid">
                  <div className="form-field span-2">
                    <div className="row" style={{alignItems:'center', justifyContent:'space-between'}}>
                      <span className="lbl">Controls</span>
                      <div className="row" style={{gap:'0.5rem'}}>
                        <button className="btn sub" onClick={loadDefaultPrompts} disabled={loadingPrompts}>{loadingPrompts?'Loading…':'Load defaults'}</button>
                        <button className="btn" onClick={()=>setOverrideEnabled(v=>!v)} aria-pressed={overrideEnabled}>{overrideEnabled?'Disable overrides':'Enable overrides'}</button>
                      </div>
                    </div>
                  </div>
                  <label className="form-field">
                    <span className="lbl">Verbosity</span>
                    <select className="input" value={verbosity} onChange={e=>setVerbosity(e.target.value)} disabled={!overrideEnabled}>
                      <option value="">(model default)</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </label>
          <label className="form-field">
                    <span className="lbl">Reasoning level</span>
                    <select className="input" value={reasoning} onChange={e=>setReasoning(e.target.value)} disabled={!overrideEnabled}>
                      <option value="">(model default)</option>
            <option value="minimal">minimal</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </label>
                  <label className="form-field">
                    <span className="lbl">Max completion tokens</span>
                    <input
                      className="input"
                      type="number"
                      min={1}
                      placeholder="(model default)"
                      value={maxTokens}
                      onChange={e=>setMaxTokens(e.target.value)}
                      disabled={!overrideEnabled}
                    />
                  </label>
                  <label className="form-field span-2">
                    <span className="lbl">System Prompt</span>
                    <textarea
                      ref={sysRef}
                      className="input"
                      rows={1}
                      style={{ overflow: 'hidden', willChange: 'height' }}
                      value={sysPrompt}
                      onChange={e=>setSysPrompt(e.target.value)}
                      onInput={e=>handleInput(e.target)}
                      disabled={!overrideEnabled}
                    />
                  </label>
                  <label className="form-field span-2">
                    <span className="lbl">User Prompt</span>
                      <textarea
                        ref={userRef}
                        className="input"
                        rows={1}
                        style={{ overflow: 'hidden', willChange: 'height' }}
                        value={userPrompt}
                        onChange={e => {
                          setUserPrompt(e.target.value);
                          handleInput(e.target); // Fallback: ensure resize on change
                        }}
                        onInput={e => handleInput(e.target)}
                        disabled={!overrideEnabled}
                      />
                  </label>
                </div>
              </details>
              <div className="actions-row">
                <button className="btn primary" onClick={postWebhook} disabled={sending}>{sending? 'Sending…':'Post to /webhook'}</button>
                <button className="btn" onClick={reset}>Reset</button>
              </div>

              <div className="code-card">
                <div className="code-card-head">
                  <div className="code-title">Full example payload</div>
                  <button className="btn sub" onClick={()=>copy(fullEditEnabled ? fullPayloadText : jsonText,'example')}>{copied==='example'?'Copied':'Copy'}</button>
                  <label style={{marginLeft:'auto', display:'flex', alignItems:'center', gap: '0.5rem'}}>
                    <input
                      type="checkbox"
                      checked={fullEditEnabled}
                      onChange={(e)=>{
                        const checked = e.target.checked;
                        setFullEditEnabled(checked);
                        if (checked) setFullPayloadText(JSON.stringify(payload, null, 2));
                      }}
                    />
                    <span className="lbl" style={{opacity:0.8}}>Edit</span>
                  </label>
                </div>
                {fullEditEnabled ? (
                  <textarea
                    className="input"
                    rows={12}
                    value={fullPayloadText}
                    onChange={e=>setFullPayloadText(e.target.value)}
                    style={{fontFamily:'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace'}}
                  />
                ) : (
                  <pre className="code-terminal" aria-label="example-json">{jsonText}</pre>
                )}
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
