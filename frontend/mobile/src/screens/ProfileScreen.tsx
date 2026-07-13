import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Image } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { User, Settings, Shield, LogOut } from 'lucide-react-native';

export function ProfileScreen() {
  const { colors } = useTheme();

  return (
    <View style={[styles.container, { backgroundColor: colors.bg }]}>
      <View style={[styles.header, { backgroundColor: colors.surface }]}>
        <View style={styles.avatarPlaceholder}>
          <User size={40} color={colors.cyan} />
        </View>
        <Text style={[styles.name, { color: colors.textPrimary }]}>Nitya Pandey</Text>
        <Text style={[styles.role, { color: colors.textSecondary }]}>Site Foreman • Zone A12</Text>
        <View style={[styles.badge, { backgroundColor: colors.green + '20' }]}>
          <Shield size={12} color={colors.green} style={{ marginRight: 4 }} />
          <Text style={[styles.badgeText, { color: colors.green }]}>AUTHORIZED</Text>
        </View>
      </View>

      <View style={styles.menu}>
        <TouchableOpacity style={[styles.menuItem, { borderBottomColor: colors.border }]}>
          <Settings size={20} color={colors.textPrimary} />
          <Text style={[styles.menuText, { color: colors.textPrimary }]}>Preferences</Text>
        </TouchableOpacity>
        
        <TouchableOpacity style={[styles.menuItem, { borderBottomColor: colors.border }]}>
          <Shield size={20} color={colors.textPrimary} />
          <Text style={[styles.menuText, { color: colors.textPrimary }]}>Privacy & Security</Text>
        </TouchableOpacity>

        <TouchableOpacity style={styles.menuItem}>
          <LogOut size={20} color={colors.red} />
          <Text style={[styles.menuText, { color: colors.red }]}>Log Out</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    padding: 40,
    paddingTop: 80,
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  avatarPlaceholder: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: 'rgba(0,212,255,0.1)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    borderWidth: 2,
    borderColor: '#00D4FF',
  },
  name: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  role: {
    fontSize: 14,
    marginBottom: 12,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
  },
  menu: {
    padding: 20,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    borderBottomWidth: 1,
  },
  menuText: {
    fontSize: 16,
    marginLeft: 16,
    fontWeight: '500',
  }
});
