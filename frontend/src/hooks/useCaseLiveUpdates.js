import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getApiBaseUrl, httpClient } from '../api/httpClient';

const SSE_EVENTS = [
  'claim.reviewed',
  'question.answered',
  'question.reviewed',
  'version.approved',
  'responsibility.updated',
  'case.acknowledged',
];

const POLL_FALLBACK_MS = 20000;

/**
 * Subscribe to real-time SSE updates for a handover case using short-lived
 * single-use stream tickets, with clean fallback to 20s TanStack Query polling
 * if SSE disconnects or multi-worker deployments miss local fan-out.
 */
export function useCaseLiveUpdates(caseId, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState('idle');
  const timerRef = useRef(null);

  useEffect(() => {
    if (!caseId || !enabled) {
      setMode('idle');
      return undefined;
    }

    let cancelled = false;
    let eventSource = null;

    const invalidateForEvent = (eventType) => {
      if (eventType === 'claim.reviewed') {
        queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
        queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      } else if (eventType === 'question.answered' || eventType === 'question.reviewed') {
        queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
        queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      } else if (eventType === 'version.approved') {
        queryClient.invalidateQueries({ queryKey: ['case', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-versions', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
        queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
        queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', caseId] });
        queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
        queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      } else if (eventType === 'responsibility.updated' || eventType === 'case.acknowledged') {
        queryClient.invalidateQueries({ queryKey: ['case', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-responsibilities', caseId] });
        queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', caseId] });
        queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
        queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      }
    };

    const startPollingFallback = () => {
      if (cancelled || timerRef.current) return;
      setMode('polling');
      timerRef.current = window.setInterval(() => {
        if (document.visibilityState === 'hidden') return;
        queryClient.invalidateQueries({ queryKey: ['case', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
        queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
        queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', caseId] });
      }, POLL_FALLBACK_MS);
    };

    const connect = async () => {
      if (typeof window === 'undefined' || typeof window.EventSource === 'undefined') {
        startPollingFallback();
        return;
      }

      try {
        const res = await httpClient.post(`/api/v1/cases/${caseId}/events/ticket`);
        if (cancelled || !res?.ticket) {
          startPollingFallback();
          return;
        }

        const baseUrl = getApiBaseUrl();
        const streamUrl = `${baseUrl}/api/v1/cases/${caseId}/events/stream?ticket=${encodeURIComponent(res.ticket)}`;
        eventSource = new window.EventSource(streamUrl, { withCredentials: true });

        eventSource.addEventListener('connected', () => {
          if (!cancelled) {
            setMode('live');
          }
        });

        SSE_EVENTS.forEach((evtName) => {
          eventSource.addEventListener(evtName, () => {
            if (!cancelled) {
              invalidateForEvent(evtName);
            }
          });
        });

        eventSource.onerror = () => {
          // Single-use stream tickets cannot be reused by browser auto-reconnect.
          if (eventSource) {
            eventSource.close();
            eventSource = null;
          }
          startPollingFallback();
        };
      } catch {
        startPollingFallback();
      }
    };

    connect();

    return () => {
      cancelled = true;
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [caseId, enabled, queryClient]);

  return { mode };
}
