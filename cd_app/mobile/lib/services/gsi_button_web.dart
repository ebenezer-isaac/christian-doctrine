import 'package:flutter/widgets.dart';
import 'package:google_sign_in_web/web_only.dart' as web;

/// Google's official Identity Services button. On web, programmatic signIn()
/// is unsupported, so this rendered button is the sanctioned sign-in trigger.
Widget renderGoogleButton() => web.renderButton();
