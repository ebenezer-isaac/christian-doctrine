/// Build time configuration.
///
/// Override at run time with --dart-define, e.g.
///   flutter run --dart-define=BACKEND_BASE_URL=https://doctrine.example.com \
///               --dart-define=GOOGLE_SERVER_CLIENT_ID=xxxx.apps.googleusercontent.com \
///               --dart-define=APP_BEARER_TOKEN=...
class AppConfig {
  static const backendBaseUrl = String.fromEnvironment(
    'BACKEND_BASE_URL',
    defaultValue: 'https://doctrine.example.com',
  );

  /// The OAuth client ID whose audience the backend trusts. On Android this is
  /// the "Web" client ID passed as serverClientId so the ID token audience
  /// matches what the backend verifies.
  static const googleServerClientId = String.fromEnvironment(
    'GOOGLE_SERVER_CLIENT_ID',
  );

  /// Shared bearer secret (must equal CD_APP_APP_BEARER_TOKEN on the backend).
  static const appBearerToken = String.fromEnvironment('APP_BEARER_TOKEN');
}
