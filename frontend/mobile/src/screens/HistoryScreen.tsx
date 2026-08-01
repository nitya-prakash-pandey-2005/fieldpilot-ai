import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View,
} from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { Clock, WifiOff } from 'lucide-react-native';
import config from '../config';

type Interaction = {
  id: string;
  kind: string;
  query: string | null;
  result: string | null;
  verdict: string | null;
  severity: string | null;
  confidence: number | null;
  zone_code: string | null;
  agent_chain: string | null;
  latency_ms: number | null;
  created_at: string | null;
};

function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? 'Yesterday' : `${days}d ago`;
}

export function HistoryScreen() {
  const { colors, apiBaseUrl } = useTheme();
  const [items, setItems] = useState<Interaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const baseUrl = apiBaseUrl || config.API_BASE_URL;
    try {
      const res = await fetch(`${baseUrl}/api/v1/interactions?limit=50`, {
        headers: { 'Bypass-Tunnel-Reminder': 'true' },
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? `HTTP ${res.status}`);
      setItems(Array.isArray(body?.data) ? body.data : []);
      // The endpoint degrades rather than 500s when its store is unavailable,
      // so an empty list can mean either "nothing yet" or "cannot read". Show
      // which, instead of an ambiguous blank screen.
      setError(body?.status === 'degraded' ? (body?.error ?? 'History unavailable') : null);
    } catch (e: any) {
      setError(`Can't reach the server at ${baseUrl}. Check the API URL in Profile.`);
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  const verdictColor = (v: string | null) => {
    switch ((v ?? '').toUpperCase()) {
      case 'PASS': return colors.success;
      case 'FAIL': return colors.error;
      case 'UNCERTAIN': return colors.warning;
      default: return colors.cyan;
    }
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.bg }]}>
      <View style={styles.header}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Interaction History</Text>
        <Text style={[styles.headerSub, { color: colors.textSecondary }]}>
          {items.length > 0 ? `${items.length} recent` : 'Your scans, questions and measurements'}
        </Text>
      </View>

      {loading ? (
        <View style={styles.centered}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
          }
        >
          {error && (
            <View style={[styles.card, { backgroundColor: colors.errorSoft, borderColor: colors.error }]}>
              <View style={styles.cardHeader}>
                <WifiOff size={14} color={colors.error} />
                <Text style={[styles.errorText, { color: colors.error }]}>{error}</Text>
              </View>
            </View>
          )}

          {!error && items.length === 0 && (
            <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
              <Text style={[styles.query, { color: colors.text }]}>No activity yet</Text>
              <Text style={[styles.result, { color: colors.textSecondary }]}>
                Scans, voice questions and measurements you make will appear here.
              </Text>
            </View>
          )}

          {items.map(item => (
            <View
              key={item.id}
              style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}
            >
              <View style={styles.cardHeader}>
                <View style={styles.badgeRow}>
                  <View style={[styles.badge, { backgroundColor: colors.cyan + '20' }]}>
                    <Text style={[styles.badgeText, { color: colors.cyan }]}>
                      {item.kind.toUpperCase()}
                    </Text>
                  </View>
                  {item.verdict && (
                    <View style={[styles.badge, { backgroundColor: verdictColor(item.verdict) + '20' }]}>
                      <Text style={[styles.badgeText, { color: verdictColor(item.verdict) }]}>
                        {item.verdict}
                      </Text>
                    </View>
                  )}
                  {item.zone_code && (
                    <Text style={[styles.zone, { color: colors.textSecondary }]}>
                      Zone {item.zone_code}
                    </Text>
                  )}
                </View>
                <View style={styles.timeContainer}>
                  <Clock size={12} color={colors.textSecondary} />
                  <Text style={[styles.time, { color: colors.textSecondary }]}>
                    {relativeTime(item.created_at)}
                  </Text>
                </View>
              </View>

              <Text style={[styles.query, { color: colors.text }]}>
                {item.query ?? '—'}
              </Text>
              {item.result && (
                <View style={[styles.resultBox, { backgroundColor: colors.bg }]}>
                  <Text style={[styles.result, { color: colors.textSecondary }]}>{item.result}</Text>
                </View>
              )}

              {(item.agent_chain || item.latency_ms != null || item.confidence != null) && (
                <View style={styles.metaRow}>
                  {item.agent_chain && (
                    <Text style={[styles.meta, { color: colors.textSecondary }]}>
                      {item.agent_chain}
                    </Text>
                  )}
                  <Text style={[styles.meta, { color: colors.textSecondary }]}>
                    {item.confidence != null ? `conf ${(item.confidence * 100).toFixed(0)}%` : ''}
                    {item.confidence != null && item.latency_ms != null ? '  ·  ' : ''}
                    {item.latency_ms != null ? `${Math.round(item.latency_ms)}ms` : ''}
                  </Text>
                </View>
              )}
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    padding: 20,
    paddingTop: 60,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  headerTitle: { fontSize: 24, fontWeight: 'bold' },
  headerSub: { fontSize: 13, marginTop: 4 },
  scrollContent: { padding: 16, gap: 12 },
  card: { padding: 16, borderRadius: 12, borderWidth: 1 },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    gap: 8,
  },
  badgeRow: { flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 },
  badge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4 },
  badgeText: { fontSize: 10, fontWeight: 'bold', letterSpacing: 1 },
  zone: { fontSize: 11 },
  timeContainer: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  time: { fontSize: 12 },
  query: { fontSize: 16, fontWeight: '600', marginBottom: 8 },
  resultBox: { padding: 12, borderRadius: 8 },
  result: { fontSize: 14, fontStyle: 'italic' },
  metaRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 10,
    gap: 8,
  },
  meta: { fontSize: 10, opacity: 0.8 },
  errorText: { fontSize: 13, flexShrink: 1 },
});
