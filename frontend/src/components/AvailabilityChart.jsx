import React from 'react';
import {
  Chart as ChartJS,
  CategoryScale, LinearScale,
  PointElement, LineElement,
  Title, Tooltip, Legend, Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

export default function AvailabilityChart({ data, service }) {
  if (!data || data.length === 0) {
    return <div className="chart-empty">No data available</div>;
  }

  // Convert Unix timestamps to HH:MM strings for the X axis labels
  const labels = data.map(d =>
    new Date(d.timestamp * 1000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  );
  const values = data.map(d => d.value);
  // Set Y axis minimum slightly below the lowest value so the line is never flush with the bottom
  const minVal = Math.min(...values);

  const chartData = {
    labels,
    datasets: [{
      label: `Availability ${service}`,
      data: values,
      borderColor: '#6366f1',
      backgroundColor: 'rgba(99,102,241,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    }],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      y: {
        min: Math.max(0, minVal - 2),
        max: 100,
        ticks: { callback: v => `${v}%`, color: '#94a3b8' },
        grid: { color: 'rgba(148,163,184,0.1)' },
      },
      x: {
        ticks: { color: '#94a3b8', maxTicksLimit: 12 },
        grid: { color: 'rgba(148,163,184,0.1)' },
      },
    },
    plugins: {
      legend: { labels: { color: '#e2e8f0' } },
      // Show three decimal places in the tooltip to match the backend precision
      tooltip: { callbacks: { label: ctx => `${ctx.parsed.y.toFixed(3)}%` } },
    },
  };

  return (
    <div className="chart-container">
      <Line data={chartData} options={options} />
    </div>
  );
}
