import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Editorial theme: Fraunces (serif) for display/headings gives scriptural
/// gravitas, Inter for body keeps it clean. Deep, layered dark surfaces with an
/// indigo primary and a gold accent drawn from the app mark.
class AppTheme {
  static const seed = Color(0xFF5B6EF5); // indigo
  static const gold = Color(0xFFE8C877); // accent
  static const inkDark = Color(0xFF0B0D12);
  static const surfaceDark = Color(0xFF12151D);

  static ThemeData light() => _build(Brightness.light);
  static ThemeData dark() => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    var scheme = ColorScheme.fromSeed(seedColor: seed, brightness: brightness);
    if (isDark) {
      scheme = scheme.copyWith(
        surface: surfaceDark,
        onSurface: const Color(0xFFE8EAF2),
        onSurfaceVariant: const Color(0xFFAAB0C2),
        primary: const Color(0xFF9AA6FF),
        tertiary: gold,
      );
    } else {
      scheme = scheme.copyWith(tertiary: const Color(0xFFB8912F));
    }

    final base = ThemeData(colorScheme: scheme, useMaterial3: true);
    final bodyText = GoogleFonts.interTextTheme(base.textTheme);
    final text = bodyText.copyWith(
      displayLarge: GoogleFonts.fraunces(
          textStyle: bodyText.displayLarge, fontWeight: FontWeight.w600, letterSpacing: -1),
      displayMedium: GoogleFonts.fraunces(
          textStyle: bodyText.displayMedium, fontWeight: FontWeight.w600, letterSpacing: -1),
      displaySmall: GoogleFonts.fraunces(
          textStyle: bodyText.displaySmall, fontWeight: FontWeight.w600),
      headlineMedium: GoogleFonts.fraunces(
          textStyle: bodyText.headlineMedium, fontWeight: FontWeight.w600),
      headlineSmall: GoogleFonts.fraunces(
          textStyle: bodyText.headlineSmall, fontWeight: FontWeight.w600),
      titleLarge: GoogleFonts.fraunces(
          textStyle: bodyText.titleLarge, fontWeight: FontWeight.w600),
      bodyLarge: GoogleFonts.inter(fontSize: 17, height: 1.75, color: scheme.onSurface),
      bodyMedium: GoogleFonts.inter(fontSize: 15, height: 1.6, color: scheme.onSurface),
    );

    return base.copyWith(
      scaffoldBackgroundColor: isDark ? inkDark : const Color(0xFFF7F7FB),
      textTheme: text,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: isDark ? const Color(0xFF161A24) : Colors.white,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: scheme.onSurface.withValues(alpha: 0.08)),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(30)),
          padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 16),
          textStyle: GoogleFonts.inter(fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: scheme.surfaceContainerHighest.withValues(alpha: 0.5),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(24),
          borderSide: BorderSide.none,
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      ),
    );
  }
}
