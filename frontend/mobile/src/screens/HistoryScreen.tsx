import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { Clock } from 'lucide-react-native';

const DEMO_HISTORY = [
  { id: 1, type: "VOICE", query: "What's the torque spec for the main beam bolts?", result: "Torque to 150 ft-lbs.", time: "Today, 10:42 AM" },
  { id: 2, type: "SCAN", query: "Rebar Inspection", result: "COMPLIANT. Spacing is correct.", time: "Today, 9:15 AM" },
  { id: 3, type: "SCAN", query: "Safety Check", result: "VIOLATION. Missing hard hat.", time: "Yesterday, 3:30 PM" },
];

export function HistoryScreen() {
  const { colors } = useTheme();

  return (
    <View style={[styles.container, { backgroundColor: colors.bg }]}>
      <View style={styles.header}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Interaction History</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scrollContent}>
        {DEMO_HISTORY.map(item => (
          <View key={item.id} style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={styles.cardHeader}>
              <View style={[styles.badge, { backgroundColor: colors.cyan + '20' }]}>
                <Text style={[styles.badgeText, { color: colors.cyan }]}>{item.type}</Text>
              </View>
              <View style={styles.timeContainer}>
                <Clock size={12} color={colors.textSecondary} />
                <Text style={[styles.time, { color: colors.textSecondary }]}>{item.time}</Text>
              </View>
            </View>
            
            <Text style={[styles.query, { color: colors.textPrimary }]}>{item.query}</Text>
            <View style={[styles.resultBox, { backgroundColor: colors.bg }]}>
              <Text style={[styles.result, { color: colors.textSecondary }]}>{item.result}</Text>
            </View>
          </View>
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
    marginBottom: 12,
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
  },
  timeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  time: {
    fontSize: 12,
  },
  query: {
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 8,
  },
  resultBox: {
    padding: 12,
    borderRadius: 8,
  },
  result: {
    fontSize: 14,
    fontStyle: 'italic',
  }
});
