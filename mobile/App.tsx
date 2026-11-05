import { DarkTheme, DefaultTheme, NavigationContainer, type Theme } from '@react-navigation/native';
import React, { useEffect, useMemo } from 'react';
import { StatusBar, StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useHydrated } from './src/hooks/useHydrated';
import { useIncomingShare } from './src/hooks/useIncomingShare';
import { navigationRef } from './src/navigation/ref';
import { RootNavigator } from './src/navigation/RootNavigator';
import { pruneConvertedFiles } from './src/services/files';
import { useHistory } from './src/store/history';
import { ThemeProvider, useTheme } from './src/theme/ThemeContext';
import { fonts } from './src/theme/typography';

export default function App() {
  const hydrated = useHydrated();

  useEffect(() => {
    if (!hydrated) return;
    // Fichiers convertis absents de l'historique : supprimés au démarrage.
    pruneConvertedFiles(useHistory.getState().entries.map(e => e.path)).catch(() => {});
  }, [hydrated]);

  return (
    <SafeAreaProvider>
      <ThemeProvider>{hydrated ? <Navigation /> : <Splash />}</ThemeProvider>
    </SafeAreaProvider>
  );
}

function Navigation() {
  const { colors, isDark } = useTheme();
  const onReady = useIncomingShare();

  const navTheme = useMemo<Theme>(() => {
    const base = isDark ? DarkTheme : DefaultTheme;
    return {
      ...base,
      colors: {
        ...base.colors,
        primary: colors.primary,
        background: colors.background,
        card: colors.surface,
        text: colors.text,
        border: colors.divider,
      },
      fonts: {
        regular: { fontFamily: fonts.regular, fontWeight: 'normal' },
        medium: { fontFamily: fonts.medium, fontWeight: 'normal' },
        bold: { fontFamily: fonts.bold, fontWeight: 'normal' },
        heavy: { fontFamily: fonts.extraBold, fontWeight: 'normal' },
      },
    };
  }, [colors, isDark]);

  return (
    <>
      <StatusBar barStyle={isDark ? 'light-content' : 'dark-content'} />
      <NavigationContainer ref={navigationRef} theme={navTheme} onReady={onReady}>
        <RootNavigator />
      </NavigationContainer>
    </>
  );
}

/** Le temps de relire réglages et historique (quelques ms). */
function Splash() {
  const { colors } = useTheme();
  return <View style={[styles.fill, { backgroundColor: colors.background }]} />;
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
