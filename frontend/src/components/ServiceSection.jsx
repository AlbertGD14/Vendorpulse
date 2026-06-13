import React, { useState, useEffect } from 'react';
import StatusCard from './StatusCard';
import AvailabilityChart from './AvailabilityChart';

export default function ServiceSection({ service, onEmpty }) {
  const [sloData, setSloData] = useState(null);
  const [slaData, setSlaData] = useState(null);
  const [history, setHistory] = useState([]);
  const [hours, setHours]     = useState(1);

  // Fetches SLO and SLA data for the current service in parallel
  function loadData() {
    fetch(`/api/slo/${service}`).then(r => r.json()).then(setSloData);
    fetch(`/api/sla/${service}`).then(r => r.json()).then(setSlaData);
  }

  // Reload SLO/SLA data whenever the active service changes
  useEffect(() => {
    setSloData(null);
    setSlaData(null);
    loadData();
  }, [service]);

  // Reload history whenever the service or selected time window changes
  useEffect(() => {
    fetch(`/api/history/${service}?hours=${hours}`)
      .then(r => r.json())
      .then(d => setHistory(d.data ?? []));
  }, [service, hours]);

  // Notify the parent to remove this tab when both SLO and SLA lists are empty
  useEffect(() => {
    if (sloData && slaData) {
      const empty = (sloData.slos?.length ?? 0) === 0 && (slaData.slas?.length ?? 0) === 0;
      if (empty) onEmpty?.();
    }
  }, [sloData, slaData]);

  // Refreshes the cards after a deletion without remounting the whole section
  function handleDelete() {
    loadData();
  }

  return (
    <div className="service-section">
      <section className="cards-section">
        <div className="section-header">
          <h2>SLOs <span className="badge slo">Internal</span></h2>
        </div>
        <div className="cards-grid">
          {sloData?.slos?.map(slo => (
            <StatusCard key={slo.slo} data={slo} type="slo" onDelete={handleDelete} />
          )) ?? <p className="loading">Loading...</p>}
        </div>
      </section>

      <section className="cards-section">
        <div className="section-header">
          <h2>SLAs <span className="badge sla">Committed</span></h2>
        </div>
        <div className="cards-grid">
          {slaData?.slas?.map(sla => (
            <StatusCard key={sla.slo} data={sla} type="sla" onDelete={handleDelete} />
          )) ?? <p className="loading">Loading...</p>}
        </div>
      </section>

      <section className="chart-section">
        <div className="section-header">
          <h2>Availability History</h2>
          <div className="time-selector">
            {[1, 6, 24].map(h => (
              <button
                key={h}
                className={`time-btn ${hours === h ? 'active' : ''}`}
                onClick={() => setHours(h)}
              >
                {h}h
              </button>
            ))}
          </div>
        </div>
        <AvailabilityChart data={history} service={service} />
      </section>
    </div>
  );
}
