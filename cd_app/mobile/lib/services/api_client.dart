import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../models.dart';
import 'auth_service.dart';

/// Talks to the FastAPI backend. Attaches the bearer + a fresh Google ID token
/// on every request, and decodes the SSE stream for a turn.
class ApiClient {
  ApiClient(this._auth);

  final AuthService _auth;

  // Append to the base so a base that includes a path prefix (e.g. ".../api")
  // is preserved. Uri.replace(path:) would drop it.
  Uri _url(String path) => Uri.parse('${AppConfig.backendBaseUrl}$path');

  Future<Map<String, String>> _headers() async {
    final idToken = await _auth.freshIdToken();
    return {
      'Authorization': 'Bearer ${AppConfig.appBearerToken}',
      'X-Google-ID-Token': idToken ?? '',
      'Content-Type': 'application/json',
    };
  }

  Future<List<Conversation>> listConversations() async {
    final res = await http.get(
      _url('/conversations'),
      headers: await _headers(),
    );
    _ensureOk(res.statusCode, res.body);
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['conversations'] as List)
        .map((e) => Conversation.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<List<ChatMessage>> history(String sessionId) async {
    final res = await http.get(
      _url('/conversations/$sessionId/messages'),
      headers: await _headers(),
    );
    _ensureOk(res.statusCode, res.body);
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['messages'] as List)
        .map((e) => ChatMessage.fromHistoryJson(e as Map<String, dynamic>))
        .where((m) => m.text.trim().isNotEmpty)
        .toList(growable: false);
  }

  Future<void> deleteConversation(String sessionId) async {
    final res = await http.delete(
      _url('/conversations/$sessionId'),
      headers: await _headers(),
    );
    _ensureOk(res.statusCode, res.body);
  }

  Future<List<ArchiveDoc>> listArchive() async {
    final res = await http.get(_url('/archive'), headers: await _headers());
    _ensureOk(res.statusCode, res.body);
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['documents'] as List)
        .map((e) => ArchiveDoc.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<Uint8List> fetchPdf(String id) async {
    final res = await http.get(_url('/archive/$id'), headers: await _headers());
    _ensureOk(res.statusCode, '');
    return res.bodyBytes;
  }

  /// Stream a turn. Pass sessionId=null to start a new conversation.
  Stream<SseEvent> sendTurn({String? sessionId, required String prompt}) async* {
    final path = sessionId == null
        ? '/conversations'
        : '/conversations/$sessionId/messages';
    final req = http.Request('POST', _url(path))
      ..headers.addAll(await _headers())
      ..body = jsonEncode({'prompt': prompt});

    final streamed = await http.Client().send(req);
    if (streamed.statusCode >= 400) {
      final body = await streamed.stream.bytesToString();
      _ensureOk(streamed.statusCode, body);
    }

    // SSE frames are separated by a blank line; each data line is JSON.
    var buffer = '';
    await for (final chunk
        in streamed.stream.transform(utf8.decoder)) {
      buffer += chunk;
      var idx = buffer.indexOf('\n\n');
      while (idx != -1) {
        final frame = buffer.substring(0, idx);
        buffer = buffer.substring(idx + 2);
        final event = _parseFrame(frame);
        if (event != null) yield event;
        idx = buffer.indexOf('\n\n');
      }
    }
  }

  SseEvent? _parseFrame(String frame) {
    for (final line in frame.split('\n')) {
      if (line.startsWith('data:')) {
        final payload = line.substring(5).trim();
        if (payload.isEmpty) continue;
        return SseEvent.fromJson(jsonDecode(payload) as Map<String, dynamic>);
      }
    }
    return null;
  }

  void _ensureOk(int status, String body) {
    if (status == 401 || status == 403) {
      throw ApiException('Not authorized. Sign in again.');
    }
    if (status == 422) {
      throw ApiException('That message is too long. Please shorten it and try again.');
    }
    if (status >= 400) {
      throw ApiException('Request failed ($status).');
    }
  }
}

class ApiException implements Exception {
  ApiException(this.message);
  final String message;
  @override
  String toString() => message;
}
