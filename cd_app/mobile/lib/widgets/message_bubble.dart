import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../models.dart';

/// One chat bubble. User messages sit right in a primary tinted bubble;
/// assistant messages sit left, render markdown, and show tool chips plus a
/// live typing indicator while streaming.
class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUser = message.role == Role.user;
    final bg = isUser
        ? theme.colorScheme.primaryContainer
        : theme.colorScheme.surfaceContainerHighest;
    final fg = isUser
        ? theme.colorScheme.onPrimaryContainer
        : theme.colorScheme.onSurface;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: isUser ? 560 : double.infinity,
        ),
        margin: const EdgeInsets.symmetric(vertical: 6, horizontal: 8),
        padding: EdgeInsets.symmetric(
            horizontal: isUser ? 16 : 18, vertical: isUser ? 12 : 14),
        decoration: BoxDecoration(
          color: isUser ? bg : theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.35),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isUser ? 16 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 16),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (message.tools.isNotEmpty) _ToolChips(tools: message.tools),
            if (isUser)
              Text(message.text, style: TextStyle(color: fg, fontSize: 16))
            else if (message.text.isNotEmpty)
              MarkdownBody(
                data: message.text,
                selectable: true,
                styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
                  p: theme.textTheme.bodyLarge,
                  pPadding: const EdgeInsets.only(bottom: 10),
                  listBullet: theme.textTheme.bodyLarge,
                  listIndent: 22,
                  h2: theme.textTheme.titleLarge,
                  h3: theme.textTheme.titleMedium,
                  strong: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w700),
                  blockquotePadding: const EdgeInsets.only(left: 14, top: 2, bottom: 2),
                  blockquoteDecoration: BoxDecoration(
                    border: Border(
                      left: BorderSide(color: theme.colorScheme.tertiary, width: 3),
                    ),
                  ),
                ),
              ),
            if (message.streaming) const _TypingDots(),
          ],
        ),
      ),
    );
  }
}

class _ToolChips extends StatelessWidget {
  const _ToolChips({required this.tools});
  final List<String> tools;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Wrap(
        spacing: 6,
        runSpacing: 4,
        children: tools
            .map((t) => Chip(
                  label: Text(
                    t.replaceFirst('mcp__christian-doctrine__', ''),
                    style: theme.textTheme.labelSmall,
                  ),
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  avatar: const Icon(Icons.travel_explore, size: 14),
                ))
            .toList(),
      ),
    );
  }
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();
  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 900))
        ..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, __) {
          return Row(
            mainAxisSize: MainAxisSize.min,
            children: List.generate(3, (i) {
              final t = (_c.value - i * 0.2) % 1.0;
              final opacity = 0.3 + 0.7 * (t < 0.5 ? t * 2 : (1 - t) * 2);
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: Opacity(
                  opacity: opacity.clamp(0.3, 1.0),
                  child: CircleAvatar(radius: 3, backgroundColor: color),
                ),
              );
            }),
          );
        },
      ),
    );
  }
}
