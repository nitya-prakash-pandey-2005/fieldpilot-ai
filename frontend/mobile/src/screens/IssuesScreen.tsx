import React, { useState, useEffect, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, RefreshControl } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { AlertTriangle, CheckCircle } from 'lucide-react-native';
import config from '../config';

// Real GET /api/v1/projects/default-project/issues (same endpoint the web
// engineer dashboard uses) — previously this screen rendered a fixed
// DEMO_ISSUES array with no backend call at all, and wasn't even reachable
// from the tab bar (TabNavigator.tsx shadowed it with its own inline
// placeholder screen).
interface RemoteIssue {
  id: string;
  zone_code: string | null;
  issue_type: string;
  severity: string;
  status: string;
  description: string;
  created_at: string | null;
}

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins} min${mins > 1 ? 's' : ''} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function IssuesScreen() {
  const { colors, apiBaseUrl } = useTheme();
  const [issues, setIssues] = useState<RemoteIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const baseUrl = apiBaseUrl || config.API_BASE_URL;
      const res = await fetch(`${baseUrl}/api/v1/projects/default-project/issues`, {
        headers: { 'Bypass-Tunnel-Reminder': 'true' },
      });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setIssues(data.issues || []);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Could not reach the server');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = () => { setRefreshing(true); load(); };

  return (
    <View style={[styles.container, { backgroundColor: colors.bg }]}>
      <View style={styles.header}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Active Issues</Text>
      </View>

      {loading ? (
        <View style={styles.centerContent}><ActivityIndicator color={colors.cyan} /></View>
      ) : error ? (
        <View style={styles.centerContent}>
          <Text style={{ color: colors.textSecondary, textAlign: 'center', paddingHorizontal: 24 }}>{error}</Text>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.cyan} />}
        >
          {issues.length === 0 && (
            <Text style={{ color: colors.textSecondary, textAlign: 'center', marginTop: 40 }}>No open issues right now.</Text>
          )}
          {issues.map(issue => {
            const isCritical = issue.severity === 'critical';
            return (
              <TouchableOpacity
                key={issue.id}
                style={[
                  styles.card,
                  { backgroundColor: colors.surface, borderColor: colors.border },
                  isCritical ? { borderLeftWidth: 4, borderLeftColor: colors.error } : {}
                ]}
              >
                <View style={styles.cardHeader}>
                  <View style={styles.idContainer}>
                    {issue.status === 'open' ? <AlertTriangle size={14} color={isCritical ? colors.error : colors.warning} /> : <CheckCircle size={14} color={colors.success} />}
                    <Text style={[styles.issueId, { color: colors.text }]}>{issue.id.slice(0, 8)}</Text>
                  </View>
                  <Text style={[styles.timestamp, { color: colors.textSecondary }]}>{timeAgo(issue.created_at)}</Text>
                </View>

                <Text style={[styles.description, { color: colors.text }]}>{issue.description}</Text>

                <View style={styles.footer}>
                  <Text style={[styles.zone, { color: colors.cyan }]}>📍 Zone {issue.zone_code || 'n/a'}</Text>
                  <View style={[styles.badge, { backgroundColor: issue.status === 'open' ? (isCritical ? colors.error + '20' : colors.warning + '20') : colors.success + '20' }]}>
                    <Text style={[styles.badgeText, { color: issue.status === 'open' ? (isCritical ? colors.error : colors.warning) : colors.success }]}>
                      {issue.severity.toUpperCase()}
                    </Text>
                  </View>
                </View>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    padding: 20,
    paddingTop: 60,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  centerContent: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scrollContent: {
    padding: 16,
    gap: 12,
  },
  card: {
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  idContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  issueId: {
    fontSize: 14,
    fontWeight: 'bold',
    fontFamily: 'monospace',
  },
  timestamp: {
    fontSize: 12,
  },
  description: {
    fontSize: 16,
    marginBottom: 12,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  zone: {
    fontSize: 12,
    fontWeight: 'bold',
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
  }
});
