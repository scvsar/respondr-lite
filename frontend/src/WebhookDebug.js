import React, { useState, useMemo } from 'react';

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

  const jsonText = useMemo(() => pretty(payload), [payload]);

  const updateField = (k, v) => setPayload(p => ({ ...p, [k]: v }));

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
      const url = '/webhook?debug=true' + (apiKey ? `&api_key=${encodeURIComponent(apiKey)}` : '');
      const r = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const text = await r.text();
      let data = null;
      try { data = JSON.parse(text); } catch { data = { raw: text }; }
      if (!r.ok) throw new Error(data?.detail || `HTTP ${r.status}`);
      setResult(data);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSending(false);
    }
  };

  const now = () => updateField('created_at', Math.floor(Date.now()/1000));
  const newIds = () => updateField('id', crypto.randomUUID());
  const reset = () => { setPayload(defaultPayload()); setResult(null); setError(null); };

  return (
    <div className="debug-wrap">
      <h2>Webhook Debugger</h2>
      <p>Craft a message and post to <code>/webhook?debug=true</code>. The response will include the LLM prompt, raw response, parsed fields, and the stored message.</p>

      <div className="grid2">
        <div>
          <label className="lbl">Name</label>
          <input className="input" value={payload.name} onChange={e=>updateField('name', e.target.value)} />
          <label className="lbl">Group ID</label>
          <input className="input" value={payload.group_id} onChange={e=>updateField('group_id', e.target.value)} />
          <label className="lbl">Message</label>
          <textarea className="input" rows={3} value={payload.text} onChange={e=>updateField('text', e.target.value)} />
          <div className="row">
            <label className="lbl">Created At (unix seconds)</label>
            <input className="input" type="number" value={payload.created_at} onChange={e=>updateField('created_at', Number(e.target.value||0))} />
            <button className="btn" onClick={now}>Now</button>
          </div>
          <div className="row">
            <label className="lbl">API Key (optional)</label>
            <input className="input" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="if required" />
          </div>
          <div className="row">
            <button className="btn" onClick={postWebhook} disabled={sending}>{sending? 'Sending…':'Post to /webhook'}</button>
            <button className="btn" onClick={reset}>Reset</button>
          </div>
          <div className="small">Full example payload</div>
          <pre className="code" aria-label="example-json">{jsonText}</pre>
        </div>
        <div>
          <h3>Result</h3>
          {error && <div className="error">{error}</div>}
          {result && (
            <div className="result">
              <details open>
                <summary>Inputs</summary>
                <pre className="code">{pretty(result.inputs)}</pre>
              </details>
              <details open>
                <summary>Parsed</summary>
                <pre className="code">{pretty(result.parsed)}</pre>
              </details>
              {result.parsed?.llm_debug && (
                <details>
                  <summary>LLM Prompt</summary>
                  <div className="row-col">
                    <div>
                      <div className="small">System</div>
                      <pre className="code">{result.parsed.llm_debug.sys_prompt}</pre>
                    </div>
                    <div>
                      <div className="small">User</div>
                      <pre className="code">{result.parsed.llm_debug.user_prompt}</pre>
                    </div>
                  </div>
                </details>
              )}
              {result.parsed?.llm_debug?.raw_response && (
                <details>
                  <summary>LLM Raw Response</summary>
                  <pre className="code">{result.parsed.llm_debug.raw_response}</pre>
                </details>
              )}
              <details>
                <summary>Stored Message</summary>
                <pre className="code">{pretty(result.stored_message)}</pre>
              </details>
            </div>
          )}
        </div>
      </div>

      <style>{`
        .debug-wrap { padding: 16px; }
        .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .lbl { display:block; font-weight:600; margin-top:8px; }
        .input { width:100%; padding:8px; box-sizing: border-box; margin-bottom:8px; }
        .row { display:flex; gap:8px; align-items:center; }
        .row-col { display:grid; grid-template-columns: 1fr 1fr; gap:12px; }
        .btn { padding:8px 12px; }
        .code { background:#111; color:#0f0; padding:8px; border-radius:4px; max-height:280px; overflow:auto; }
        .error { color:#b00; font-weight:600; }
        .small { color:#666; font-size: 12px; margin-top:8px; }
        h3 { margin-top:0; }
        details { margin-bottom: 8px; }
        summary { cursor: pointer; }
        @media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
