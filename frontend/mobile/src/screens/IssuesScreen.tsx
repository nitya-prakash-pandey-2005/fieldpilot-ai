import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { AlertTriangle, CheckCircle, Clock } from 'lucide-react-native';

const DEMO_ISSUES = [
  { id: "OBS-049", severity: "critical", description: "Unsecured rebar caps on Column C4", zone: "Zone A12", timestamp: "Just now", status: "open" },
  { id: "OBS-048", severity: "warning", description: "Water pooling near generator", zone: "Zone D4", timestamp: "12 mins ago", status: "open" },
  { id: "OBS-047", severity: "high", description: "Missing fall protection harness", zone: "Zone A12", timestamp: "45 mins ago", status: "resolved" },
];

export function IssuesScreen() {
  const { colors } = useTheme();
  
  return (
    <View style={[styles.container, { backgroundColor: colors.bg }]}>
      <View style={styles.header}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Active Issues</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scrollContent}>
        {DEMO_ISSUES.map(issue => (
          <TouchableOpacity 
            key={issue.id} 
            style={[
              styles.card, 
              { backgroundColor: colors.surface, borderColor: colors.border },
              issue.severity === 'critical' ? { borderLeftWidth: 4, borderLeftColor: colors.red } : {}
            ]}
          >
            <View style={styles.cardHeader}>
              <View style={styles.idContainer}>
                {issue.status === 'open' ? <AlertTriangle size={14} color={issue.severity === 'critical' ? colors.red : colors.amber} /> : <CheckCircle size={14} color={colors.green} />}
                <Text style={[styles.issueId, { color: colors.textPrimary }]}>{issue.id}</Text>
              </View>
              <Text style={[styles.timestamp, { color: colors.textSecondary }]}>{issue.timestamp}</Text>
            </View>
            
            <Text style={[styles.description, { color: colors.textPrimary }]}>{issue.description}</Text>
            
            <View style={styles.footer}>
              <Text style={[styles.zone, { color: colors.cyan }]}>📍 {issue.zone}</Text>
              <View style={[styles.badge, { backgroundColor: issue.status === 'open' ? (issue.severity === 'critical' ? colors.red + '20' : colors.amber + '20') : colors.green + '20' }]}>
                <Text style={[styles.badgeText, { color: issue.status === 'open' ? (issue.severity === 'critical' ? colors.red : colors.amber) : colors.green }]}>
                  {issue.severity.toUpperCase()}
                </Text>
              </View>
            </View>
          </TouchableOpacity>
        ))}
      </ScrollView>
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
