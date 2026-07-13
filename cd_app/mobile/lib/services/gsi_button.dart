// Platform-split: the web implementation renders Google's GIS button; every
// other platform gets a no-op stub (mobile signs in via AuthService.signIn()).
export 'gsi_button_stub.dart' if (dart.library.js_interop) 'gsi_button_web.dart';
