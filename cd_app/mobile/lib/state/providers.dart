import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';

final authServiceProvider = Provider<AuthService>((ref) => AuthService());

final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(ref.watch(authServiceProvider)),
);

/// Whether the user is signed in. Flipped by the sign-in screen.
final signedInProvider = StateProvider<bool>((ref) => false);

/// The doctrine PDF archive listing.
final archiveProvider = FutureProvider.autoDispose<List<ArchiveDoc>>(
  (ref) => ref.watch(apiClientProvider).listArchive(),
);

/// The conversation list, refreshable.
final conversationsProvider =
    FutureProvider.autoDispose<List<Conversation>>((ref) async {
  ref.watch(signedInProvider); // refetch after sign-in
  return ref.watch(apiClientProvider).listConversations();
});

/// Immutable chat state for the active conversation.
@immutable
class ChatState {
  final String? sessionId; // null => a brand new, not yet saved conversation
  final List<ChatMessage> messages;
  final bool sending;
  final String? error;

  const ChatState({
    this.sessionId,
    this.messages = const [],
    this.sending = false,
    this.error,
  });

  ChatState copyWith({
    Object? sessionId = _unset,
    List<ChatMessage>? messages,
    bool? sending,
    Object? error = _unset,
  }) =>
      ChatState(
        sessionId:
            sessionId == _unset ? this.sessionId : sessionId as String?,
        messages: messages ?? this.messages,
        sending: sending ?? this.sending,
        error: error == _unset ? this.error : error as String?,
      );

  static const _unset = Object();
}

class ChatController extends StateNotifier<ChatState> {
  ChatController(this._ref) : super(const ChatState());

  final Ref _ref;

  /// Clear to a fresh conversation. This is the "new chat" / clear action.
  void startNew() => state = const ChatState();

  /// Load an existing conversation's transcript.
  Future<void> open(String sessionId) async {
    state = ChatState(sessionId: sessionId, sending: true);
    try {
      final msgs = await _ref.read(apiClientProvider).history(sessionId);
      state = ChatState(sessionId: sessionId, messages: msgs);
    } catch (e) {
      state = ChatState(sessionId: sessionId, error: e.toString());
    }
  }

  Future<void> send(String prompt) async {
    if (state.sending || prompt.trim().isEmpty) return;
    final withUser = [
      ...state.messages,
      ChatMessage(role: Role.user, text: prompt.trim()),
      const ChatMessage(role: Role.assistant, text: '', streaming: true),
    ];
    state = state.copyWith(messages: withUser, sending: true, error: null);

    final api = _ref.read(apiClientProvider);
    final tools = <String>[];
    final buffer = StringBuffer();
    String? newSessionId = state.sessionId;

    try {
      await for (final ev
          in api.sendTurn(sessionId: state.sessionId, prompt: prompt.trim())) {
        switch (ev.type) {
          case 'session':
            newSessionId = ev.sessionId ?? newSessionId;
          case 'tool':
            if (ev.name != null && !tools.contains(ev.name)) tools.add(ev.name!);
            _updateLast(buffer.toString(), tools, streaming: true);
          case 'delta':
            buffer.write(ev.text ?? '');
            _updateLast(buffer.toString(), tools, streaming: true);
          case 'done':
            newSessionId = ev.sessionId ?? newSessionId;
            _updateLast(buffer.toString(), tools, streaming: false);
          case 'error':
            state = state.copyWith(
              sending: false,
              error: 'The engine hit an error (${ev.message}).',
            );
            return;
        }
      }
      state = state.copyWith(sessionId: newSessionId, sending: false);
      // Refresh the drawer so a new conversation appears.
      _ref.invalidate(conversationsProvider);
    } catch (e) {
      state = state.copyWith(sending: false, error: e.toString());
    }
  }

  void _updateLast(String text, List<String> tools, {required bool streaming}) {
    if (state.messages.isEmpty) return;
    final msgs = [...state.messages];
    msgs[msgs.length - 1] = msgs.last.copyWith(
      text: text,
      tools: [...tools],
      streaming: streaming,
    );
    state = state.copyWith(messages: msgs);
  }
}

final chatControllerProvider =
    StateNotifierProvider<ChatController, ChatState>(
  (ref) => ChatController(ref),
);
