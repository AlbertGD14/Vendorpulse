import React, { useState } from 'react';

const WINDOWS = { slo: ['1h', '6h', '24h', '7d'], sla: ['7d', '30d'] };
const CONDITIONS = ['<=', '>=', '<', '>', '==', '!='];

export default function CreateSLOForm({ services, onClose, onCreated }) {
  const [form, setForm] = useState({
    service: services[0] || '',
    check: '',
    type: 'slo',
    target: 99,
    window: '1h',
    description: '',
    mode: 'simulated',
    real_prometheus_url: 'http://host.docker.internal:9090',
    real_query: '',
    real_threshold: '',
    real_condition: '<=',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [metrics, setMetrics] = useState([]);
  const [metricFilter, setMetricFilter] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState(null);

  function set(field, value) {
    setForm(f => ({ ...f, [field]: value }));
  }

  function handleTypeChange(type) {
    setForm(f => ({
      ...f,
      type,
      window: type === 'sla' ? '30d' : '1h',
      target: type === 'sla' ? 95 : 99,
    }));
  }

  async function handleDiscover() {
    setDiscovering(true);
    setDiscoverError(null);
    setMetrics([]);
    try {
      const res = await fetch(`/api/prometheus/metrics?url=${encodeURIComponent(form.real_prometheus_url)}`);
      const data = await res.json();
      if (data.metrics && data.metrics.length > 0) {
        setMetrics(data.metrics);
        setMetricFilter('');
      } else {
        setDiscoverError('No metrics found at that URL');
      }
    } catch {
      setDiscoverError('Could not connect to Prometheus');
    } finally {
      setDiscovering(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const payload = {
        ...form,
        real_threshold: form.real_threshold !== '' ? parseFloat(form.real_threshold) : null,
      };
      const res = await fetch('/api/slo/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        onCreated(data.name);
        onClose();
      }
    } catch {
      setError('Connection error with the backend');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Create new SLO / SLA</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <form onSubmit={handleSubmit} className="slo-form">

          <div className="form-row">
            <label>Service</label>
            <input
              list="svc-list"
              value={form.service}
              onChange={e => set('service', e.target.value)}
              placeholder="e.g. cv-analyzer"
              required
            />
            <datalist id="svc-list">
              {services.map(s => <option key={s} value={s} />)}
            </datalist>
          </div>

          <div className="form-row">
            <label>Check</label>
            <input
              list="check-list"
              value={form.check}
              onChange={e => set('check', e.target.value)}
              placeholder="e.g. latency"
              required
            />
            <datalist id="check-list">
              <option value="latency" />
              <option value="quality" />
              <option value="throughput" />
              <option value="availability" />
            </datalist>
          </div>

          <div className="form-row">
            <label>Type</label>
            <div className="toggle-group">
              <button type="button" className={`toggle-btn ${form.type === 'slo' ? 'active' : ''}`}
                onClick={() => handleTypeChange('slo')}>SLO</button>
              <button type="button" className={`toggle-btn ${form.type === 'sla' ? 'active' : ''}`}
                onClick={() => handleTypeChange('sla')}>SLA</button>
            </div>
          </div>

          <div className="form-row">
            <label>Target (%)</label>
            <input
              type="number" min="1" max="99.999" step="0.1"
              value={form.target}
              onChange={e => set('target', parseFloat(e.target.value))}
              required
            />
          </div>

          <div className="form-row">
            <label>Window</label>
            <select value={form.window} onChange={e => set('window', e.target.value)}>
              {WINDOWS[form.type].map(w => <option key={w} value={w}>{w}</option>)}
            </select>
          </div>

          <div className="form-row">
            <label>Description <span className="form-optional">(optional)</span></label>
            <input
              type="text"
              value={form.description}
              onChange={e => set('description', e.target.value)}
              placeholder="Auto-generated if left empty"
            />
          </div>

          <div className="form-divider" />

          <div className="form-row">
            <label>Data source</label>
            <div className="toggle-group">
              <button type="button" className={`toggle-btn ${form.mode === 'simulated' ? 'active' : ''}`}
                onClick={() => set('mode', 'simulated')}>Simulated</button>
              <button type="button" className={`toggle-btn ${form.mode === 'real' ? 'active' : ''}`}
                onClick={() => set('mode', 'real')}>Real</button>
            </div>
          </div>

          {form.mode === 'real' && (
            <>
              <div className="form-row">
                <label>Prometheus URL</label>
                <div className="input-with-btn">
                  <input
                    type="text"
                    value={form.real_prometheus_url}
                    onChange={e => { set('real_prometheus_url', e.target.value); setMetrics([]); }}
                    placeholder="http://host.docker.internal:9090"
                    required
                  />
                  <button
                    type="button"
                    className="btn-discover"
                    onClick={handleDiscover}
                    disabled={discovering}
                  >
                    {discovering ? '…' : 'Discover'}
                  </button>
                </div>
                {discoverError && <p className="form-error" style={{marginTop:'0.3rem'}}>{discoverError}</p>}
                {metrics.length > 0 && (
                  <p className="form-hint">{metrics.length} metrics found</p>
                )}
              </div>

              <div className="form-row">
                <label>Metric</label>
                {metrics.length > 0 ? (
                  <>
                    <input
                      type="text"
                      value={metricFilter}
                      onChange={e => setMetricFilter(e.target.value)}
                      placeholder="Filter metrics…"
                      className="metric-filter"
                    />
                    <select
                      value={form.real_query}
                      onChange={e => set('real_query', e.target.value)}
                      required
                      size={6}
                    >
                      <option value="">Select a metric…</option>
                      {metrics
                        .filter(m => m.display.toLowerCase().includes(metricFilter.toLowerCase()))
                        .map(m => (
                          <option key={m.query} value={m.query}>{m.display}</option>
                        ))}
                    </select>
                  </>
                ) : (
                  <input
                    type="text"
                    value={form.real_query}
                    onChange={e => set('real_query', e.target.value)}
                    placeholder='e.g. avg_p_latency{service_type="CvAnalyzer"}'
                    required
                  />
                )}
              </div>

              <div className="form-row form-row-inline">
                <div className="form-row">
                  <label>Threshold</label>
                  <input
                    type="number" step="any"
                    value={form.real_threshold}
                    onChange={e => set('real_threshold', e.target.value)}
                    placeholder="e.g. 0.1"
                    required
                  />
                </div>
                <div className="form-row">
                  <label>OK condition</label>
                  <select value={form.real_condition} onChange={e => set('real_condition', e.target.value)}>
                    {CONDITIONS.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>

              <p className="form-hint">
                Check passes if: value {form.real_condition} {form.real_threshold || '?'}
              </p>
            </>
          )}

          {error && <p className="form-error">{error}</p>}

          <div className="form-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
