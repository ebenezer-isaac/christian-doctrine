import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'screens/home_screen.dart';
import 'screens/landing_screen.dart';
import 'state/providers.dart';
import 'theme/app_theme.dart';

void main() => runApp(const ProviderScope(child: ChristianDoctrineApp()));

class ChristianDoctrineApp extends ConsumerWidget {
  const ChristianDoctrineApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final signedIn = ref.watch(signedInProvider);
    return MaterialApp(
      title: 'Christian Doctrine',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      home: signedIn ? const HomeScreen() : const LandingScreen(),
    );
  }
}
