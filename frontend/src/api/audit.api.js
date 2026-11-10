/**
 * Audit log API client.
 * Phase 10 — Hardening & Demo.
 */
import { httpClient } from './httpClient';

export const auditApi = {
  getEvents(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.entity_type) searchParams.append('entity_type', params.entity_type);
    if (params.entity_id) searchParams.append('entity_id', params.entity_id);
    if (params.actor_id) searchParams.append('actor_id', params.actor_id);
    if (params.action) searchParams.append('action', params.action);
    if (params.search) searchParams.append('search', params.search);
    if (params.limit) searchParams.append('limit', params.limit);
    if (params.offset) searchParams.append('offset', params.offset);

    const query = searchParams.toString();
    return httpClient.get(`/api/v1/audit/events${query ? `?${query}` : ''}`);
  },
};
