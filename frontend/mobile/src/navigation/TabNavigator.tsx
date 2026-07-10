import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Scan, AlertTriangle, Clock, MessageSquare, User, Mic } from 'lucide-react-native';

import { ScanScreen } from '../screens/ScanScreen';
import { AskAIScreen } from '../screens/AskAIScreen';
import { VoiceScreen } from '../screens/VoiceScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { View, Text } from 'react-native';

const Tab = createBottomTabNavigator();

// Placeholder screens for MVP
const IssuesScreen = () => <View style={{flex:1, justifyContent:'center', alignItems:'center', backgroundColor: '#121212'}}><Text style={{color: 'white'}}>Active Issues</Text></View>;

export function TabNavigator() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: '#1e1e1e' },
        headerTintColor: '#fff',
        tabBarStyle: { backgroundColor: '#1e1e1e', borderTopColor: '#333' },
        tabBarActiveTintColor: '#3b82f6',
        tabBarInactiveTintColor: '#888',
      }}
    >
      <Tab.Screen 
        name="SCAN" 
        component={ScanScreen} 
        options={{
          tabBarIcon: ({ color, size }) => <Scan color={color} size={size} />
        }}
      />
      <Tab.Screen 
        name="ISSUES" 
        component={IssuesScreen} 
        options={{
          tabBarIcon: ({ color, size }) => <AlertTriangle color={color} size={size} />
        }}
      />
      <Tab.Screen 
        name="VOICE" 
        component={VoiceScreen} 
        options={{
          tabBarIcon: ({ color, size }) => <Mic color={color} size={size} />
        }}
      />
      <Tab.Screen 
        name="ASK AI" 
        component={AskAIScreen} 
        options={{
          tabBarIcon: ({ color, size }) => <MessageSquare color={color} size={size} />
        }}
      />
      <Tab.Screen 
        name="PROFILE" 
        component={ProfileScreen} 
        options={{
          tabBarIcon: ({ color, size }) => <User color={color} size={size} />
        }}
      />
    </Tab.Navigator>
  );
}
