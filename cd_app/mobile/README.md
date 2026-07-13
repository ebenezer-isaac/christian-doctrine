# Christian Doctrine, mobile app

Flutter client for the private doctrine engine companion. Google Sign-In,
conversation list, streaming answers, one tap new/clear conversation.

## Architecture

```
lib/
  config.dart              build time config (backend URL, Google client, bearer)
  models.dart              Conversation, ChatMessage, SseEvent
  theme/app_theme.dart     Material 3 light + dark
  services/
    auth_service.dart      Google Sign-In (isolated; swap here for v7 API)
    api_client.dart        REST + SSE streaming to the backend
  state/providers.dart     Riverpod: auth, conversations, chat controller
  screens/
    sign_in_screen.dart
    home_screen.dart       app bar + drawer + chat
  widgets/
    conversation_drawer.dart   list, new conversation, swipe to delete, sign out
    chat_view.dart             message list + composer + autoscroll
    message_bubble.dart        markdown, tool chips, typing dots
```

State flows one way: `ChatController` owns the active conversation, streams
SSE events from the backend, and grows the assistant bubble live. "New
conversation" clears local state so the next send opens a fresh backend session.

## Setup

This is `lib/` + `pubspec.yaml` only, to avoid committing generated platform
folders. To run:

```bash
cd cd_app/mobile
flutter create .          # generate android/ ios/ etc. into this folder
flutter pub get
```

### Google Sign-In

1. Create OAuth credentials in Google Cloud Console (Android + a Web client).
2. The backend verifies the ID token audience, so pass the Web client ID as the
   server client ID (see `--dart-define` below) and add it to the backend's
   `CD_APP_GOOGLE_CLIENT_IDS`.
3. Add every allowed account to the backend `CD_APP_ALLOWED_EMAILS`.

### Run with config

```bash
flutter run \
  --dart-define=BACKEND_BASE_URL=https://doctrine.example.com \
  --dart-define=GOOGLE_SERVER_CLIENT_ID=xxxx.apps.googleusercontent.com \
  --dart-define=APP_BEARER_TOKEN=<same as CD_APP_APP_BEARER_TOKEN>
```

## Notes

- Written against `google_sign_in` 6.x. If you adopt 7.x, only
  `auth_service.dart` changes (the call surface moved to
  `GoogleSignIn.instance` + `authenticate()`).
- The bearer token ships in the client via dart-define. It is a coarse gate, not
  a user secret; the real per-user check is the Google identity on the backend.
- Streaming uses plain SSE over `http`. No extra socket dependency.
