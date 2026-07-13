import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../screens/archive_screen.dart';
import '../state/providers.dart';

class ConversationDrawer extends ConsumerWidget {
  const ConversationDrawer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final convos = ref.watch(conversationsProvider);
    final activeId = ref.watch(chatControllerProvider).sessionId;

    return Drawer(
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Row(
                children: [
                  Icon(Icons.menu_book_rounded,
                      color: theme.colorScheme.primary),
                  const SizedBox(width: 12),
                  Text('Christian Doctrine',
                      style: theme.textTheme.titleMedium),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: FilledButton.tonalIcon(
                onPressed: () {
                  ref.read(chatControllerProvider.notifier).startNew();
                  Navigator.of(context).pop();
                },
                icon: const Icon(Icons.add),
                label: const Text('New conversation'),
                style: FilledButton.styleFrom(
                  minimumSize: const Size.fromHeight(44),
                ),
              ),
            ),
            const Divider(height: 24),
            Expanded(
              child: convos.when(
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text('Could not load conversations.\n$e',
                        textAlign: TextAlign.center),
                  ),
                ),
                data: (list) => list.isEmpty
                    ? const Center(child: Text('No conversations yet'))
                    : ListView.builder(
                        itemCount: list.length,
                        itemBuilder: (_, i) {
                          final c = list[i];
                          return Dismissible(
                            key: ValueKey(c.sessionId),
                            direction: DismissDirection.endToStart,
                            background: Container(
                              color: theme.colorScheme.errorContainer,
                              alignment: Alignment.centerRight,
                              padding: const EdgeInsets.only(right: 20),
                              child: const Icon(Icons.delete_outline),
                            ),
                            onDismissed: (_) async {
                              await ref
                                  .read(apiClientProvider)
                                  .deleteConversation(c.sessionId);
                              ref.invalidate(conversationsProvider);
                            },
                            child: ListTile(
                              selected: c.sessionId == activeId,
                              leading: const Icon(Icons.chat_bubble_outline),
                              title: Text(c.title,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis),
                              onTap: () {
                                ref
                                    .read(chatControllerProvider.notifier)
                                    .open(c.sessionId);
                                Navigator.of(context).pop();
                              },
                            ),
                          );
                        },
                      ),
              ),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.library_books_outlined),
              title: const Text('Doctrine archive'),
              onTap: () {
                Navigator.of(context).pop();
                Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const ArchiveScreen()),
                );
              },
            ),
            ListTile(
              leading: const Icon(Icons.logout),
              title: const Text('Sign out'),
              onTap: () async {
                await ref.read(authServiceProvider).signOut();
                ref.read(signedInProvider.notifier).state = false;
              },
            ),
          ],
        ),
      ),
    );
  }
}
