import { Platform } from 'react-native';

const getApiUrl = () => {
  if (__DEV__) {
    if (Platform.OS === 'web') {
      return process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';
    }
    if (Platform.OS === 'android') {
      return process.env.EXPO_PUBLIC_API_URL ?? 'http://10.0.2.2:8000';
    }
    if (Platform.OS === 'ios') {
      return process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';
    }
  }
  return process.env.EXPO_PUBLIC_API_URL ?? 'http://192.168.1.6:8000';
};

const config = {
  API_BASE_URL: getApiUrl(),
  WS_BASE_URL: getApiUrl().replace('http', 'ws'),
};

export default config;
