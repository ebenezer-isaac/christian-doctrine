import 'dart:html' as html;
import 'dart:typed_data';

/// Open (or download) PDF bytes on web via a blob URL. Fetching with auth
/// headers then blobbing avoids exposing an unauthenticated file URL.
void openPdf(Uint8List bytes, String filename, {bool download = false}) {
  final blob = html.Blob(<Object>[bytes], 'application/pdf');
  final url = html.Url.createObjectUrlFromBlob(blob);
  final anchor = html.AnchorElement(href: url);
  if (download) {
    anchor.download = filename;
  } else {
    anchor.target = '_blank';
  }
  anchor.click();
  html.Url.revokeObjectUrl(url);
}

/// Open a URL in a new tab (used for the APK download link on web).
void openUrl(String url) => html.window.open(url, '_blank');
