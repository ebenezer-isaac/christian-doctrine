import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:google_sign_in/google_sign_in.dart';

import '../config.dart';

/// Google Sign-In wrapper.
///
/// Web and mobile differ: on the web, `signIn()` is unsupported, so the UI
/// shows Google's rendered GIS button and the resulting account arrives on
/// `onUserChanged`; we `adopt()` it to capture the ID token. On mobile,
/// `signIn()` is the interactive entry point. The ID token (audience = our web
/// client id) is what the backend verifies.
class AuthService {
  AuthService()
      : _google = GoogleSignIn(
          scopes: const ['email'],
          clientId: kIsWeb ? _clientId : null,
          serverClientId: kIsWeb ? null : _clientId,
        );

  static String? get _clientId =>
      AppConfig.googleServerClientId.isEmpty ? null : AppConfig.googleServerClientId;

  final GoogleSignIn _google;
  GoogleSignInAccount? _account;
  String? _idToken;

  String? get email => _account?.email;
  String? get idToken => _idToken;
  Stream<GoogleSignInAccount?> get onUserChanged => _google.onCurrentUserChanged;

  /// Try to restore a prior session silently (no UI).
  Future<void> initSilent() async {
    try {
      await _google.signInSilently();
    } catch (_) {
      // no prior session; ignore
    }
  }

  /// Capture tokens from an account the platform surfaced (web GIS button or
  /// silent restore). Returns true when a usable ID token is present.
  Future<bool> adopt(GoogleSignInAccount? account) async {
    if (account == null) return false;
    final auth = await account.authentication;
    _account = account;
    _idToken = auth.idToken;
    return _idToken != null;
  }

  /// Interactive sign-in for mobile. Web uses the rendered GIS button instead.
  Future<bool> signIn() async => adopt(await _google.signIn());

  /// A fresh ID token for a backend call (silently refreshed if needed).
  Future<String?> freshIdToken() async {
    final account = _account ?? await _google.signInSilently();
    if (account == null) return null;
    final auth = await account.authentication;
    _account = account;
    _idToken = auth.idToken;
    return _idToken;
  }

  Future<void> signOut() async {
    await _google.signOut();
    _account = null;
    _idToken = null;
  }
}
