import React, { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

type ServiceState = {
  status: 'ready' | 'connected' | 'rate_limited' | 'auth_error' | 'invalid_request' | 'access_denied' | 'unavailable' | 'unreachable';
  retry_after?: number;
};

type HealthResponse = {
  llm: ServiceState;
  vlm: ServiceState;
  stt: ServiceState;
  embeddings: ServiceState;
  qdrant: ServiceState;
};

export const ServiceStatus: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const fetchHealth = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/health/ai`);
        if (!response.ok) {
          throw new Error('Health check failed');
        }
        const data = await response.json();
        if (active) {
          setHealth(data);
          setError(null);
        }
      } catch (e) {
        if (active) {
          setError('AI Service Unreachable');
        }
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 5000); // Poll every 5s

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'ready':
      case 'connected':
        return '🟢';
      case 'rate_limited':
        return '🟡';
      case 'unavailable':
        return '🟠';
      default:
        return '🔴';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'ready': return 'Ready';
      case 'connected': return 'Connected';
      case 'rate_limited': return 'Rate Limited';
      case 'auth_error': return 'Authentication Error';
      case 'invalid_request': return 'Invalid AI Request';
      case 'access_denied': return 'Access Denied';
      case 'unavailable': return 'AI Provider Temporarily Unavailable';
      case 'unreachable': return 'AI Service Unreachable';
      default: return 'Error';
    }
  };

  const renderService = (name: string, label: string) => {
    if (error) {
      return (
        <div className="flex justify-between text-sm py-1">
          <span className="font-medium text-slate-700 dark:text-slate-300">{label}</span>
          <span className="text-red-500">🔴 AI Service Unreachable</span>
        </div>
      );
    }
    if (!health) {
      return (
        <div className="flex justify-between text-sm py-1">
          <span className="font-medium text-slate-700 dark:text-slate-300">{label}</span>
          <span className="text-slate-400">Loading...</span>
        </div>
      );
    }

    const s = health[name as keyof HealthResponse];
    const statusText = getStatusText(s.status);
    const icon = getStatusIcon(s.status);

    return (
      <div className="flex flex-col text-sm py-1">
        <div className="flex justify-between">
          <span className="font-medium text-slate-700 dark:text-slate-300">{label}</span>
          <span className="text-slate-600 dark:text-slate-400">
            {icon} {statusText}
          </span>
        </div>
        {s.status === 'rate_limited' && s.retry_after && (
          <span className="text-xs text-orange-500 text-right mt-1">
            Retrying in {s.retry_after}s
          </span>
        )}
      </div>
    );
  };

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg shadow-sm border border-slate-200 dark:border-slate-700 p-4 mb-4">
      <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-3 uppercase tracking-wider">AI Services</h3>
      <div className="space-y-1">
        {renderService('llm', 'LLM')}
        {renderService('vlm', 'VLM')}
        {renderService('stt', 'Whisper')}
        {renderService('embeddings', 'Embeddings')}
        {renderService('qdrant', 'Qdrant')}
      </div>
    </div>
  );
};
