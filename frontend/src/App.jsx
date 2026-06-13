import React, { useState, useEffect } from 'react';
import ServiceSection from './components/ServiceSection';
import CreateSLOForm from './components/CreateSLOForm';
import './App.css';

export default function App() {
  const [services, setServices] = useState([]);
  const [active, setActive]     = useState(null);
  const [loading, setLoading]   = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Fetches the service list from the backend and sets the first one as active if none is selected
  function loadServices() {
    return fetch('/api/services')
      .then(r => r.json())
      .then(d => {
        setServices(d.services);
        if (!active) setActive(d.services[0]);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }

  // Load services once on mount
  useEffect(() => { loadServices(); }, []);

  // Refreshes the service list after a new SLO/SLA is created
  function handleCreated() {
    loadServices();
  }

  // Removes a service tab when all its SLOs and SLAs have been deleted
  function handleServiceEmpty(service) {
    const remaining = services.filter(s => s !== service);
    setServices(remaining);
    if (active === service) setActive(remaining[0] ?? null);
  }

  return (
    <div className="app">
      <header className="header">
        <h1>SLO / SLA Dashboard</h1>
        <nav className="tabs">
          {services.map(s => (
            <button
              key={s}
              className={`tab ${active === s ? 'active' : ''}`}
              onClick={() => setActive(s)}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </nav>
        <button className="btn-create" onClick={() => setShowForm(true)}>
          + Create SLO/SLA
        </button>
      </header>

      <main className="main">
        {loading && <p className="loading">Loading services...</p>}
        {/* key={active} forces a full remount when the tab changes, resetting internal state */}
        {active && <ServiceSection key={active} service={active} onEmpty={() => handleServiceEmpty(active)} />}
      </main>

      {showForm && (
        <CreateSLOForm
          services={services}
          onClose={() => setShowForm(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
