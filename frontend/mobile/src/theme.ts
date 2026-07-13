export const theme = {
  colors: {
    bg: '#0A0A0F',
    surface: '#12121A',
    elevated: '#1A1A24',
    border: '#2A2A38',
    textPrimary: '#F0F0FF',
    textSecondary: '#A0A0B8',
    cyan: '#00D4FF',
    amber: '#FFB300',
    red: '#FF3B3B',
    green: '#00C851',
    purple: '#7B61FF',
  },
  typography: {
    fontFamily: {
      regular: 'System', // Fallback, could load custom fonts
      bold: 'System',
      mono: 'System', // Would ideally load JetBrains Mono
    }
  },
  spacing: {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
  },
  borderRadius: {
    sm: 4,
    md: 8,
    lg: 12,
    full: 9999,
  }
};
