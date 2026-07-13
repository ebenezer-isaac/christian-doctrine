import 'package:flutter/foundation.dart';

/// A conversation as listed by the backend (one SDK session).
@immutable
class Conversation {
  final String sessionId;
  final String title;
  final String lastModified;

  const Conversation({
    required this.sessionId,
    required this.title,
    required this.lastModified,
  });

  factory Conversation.fromJson(Map<String, dynamic> j) => Conversation(
        sessionId: j['session_id'] as String? ?? '',
        title: j['title'] as String? ?? 'Untitled',
        lastModified: j['last_modified'] as String? ?? '',
      );
}

/// A doctrine PDF in the archive.
@immutable
class ArchiveDoc {
  final String id;
  final String title;
  const ArchiveDoc({required this.id, required this.title});

  factory ArchiveDoc.fromJson(Map<String, dynamic> j) => ArchiveDoc(
        id: j['id'] as String? ?? '',
        title: j['title'] as String? ?? '',
      );
}

enum Role { user, assistant }

/// One rendered message. Assistant messages grow while streaming.
@immutable
class ChatMessage {
  final Role role;
  final String text;
  final List<String> tools; // tool names the agent invoked, shown as chips
  final bool streaming;

  const ChatMessage({
    required this.role,
    required this.text,
    this.tools = const [],
    this.streaming = false,
  });

  ChatMessage copyWith({String? text, List<String>? tools, bool? streaming}) =>
      ChatMessage(
        role: role,
        text: text ?? this.text,
        tools: tools ?? this.tools,
        streaming: streaming ?? this.streaming,
      );

  factory ChatMessage.fromHistoryJson(Map<String, dynamic> j) {
    final role = (j['role'] as String? ?? '').toLowerCase();
    return ChatMessage(
      role: role.contains('user') ? Role.user : Role.assistant,
      text: j['text'] as String? ?? '',
    );
  }
}

/// A decoded Server Sent Event from a streaming turn.
@immutable
class SseEvent {
  final String type; // session | delta | tool | done | error
  final String? sessionId;
  final String? text;
  final String? name;
  final String? message;

  const SseEvent({
    required this.type,
    this.sessionId,
    this.text,
    this.name,
    this.message,
  });

  factory SseEvent.fromJson(Map<String, dynamic> j) => SseEvent(
        type: j['type'] as String? ?? 'error',
        sessionId: j['session_id'] as String?,
        text: j['text'] as String?,
        name: j['name'] as String?,
        message: j['message'] as String?,
      );
}
