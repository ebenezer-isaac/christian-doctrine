import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models.dart';
import '../services/pdf_opener.dart';
import '../state/providers.dart';

/// Gated doctrine archive: search the 231 per-question PDFs, view or download.
class ArchiveScreen extends ConsumerStatefulWidget {
  const ArchiveScreen({super.key});

  @override
  ConsumerState<ArchiveScreen> createState() => _ArchiveScreenState();
}

class _ArchiveScreenState extends ConsumerState<ArchiveScreen> {
  String _query = '';
  String? _busyId;

  Future<void> _open(ArchiveDoc doc, {bool download = false}) async {
    setState(() => _busyId = doc.id);
    try {
      final bytes = await ref.read(apiClientProvider).fetchPdf(doc.id);
      openPdf(bytes, '${doc.id}.pdf', download: download);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Could not open document: $e')));
      }
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final async = ref.watch(archiveProvider);
    final q = _query.trim().toLowerCase();

    return Scaffold(
      appBar: AppBar(title: const Text('Doctrine archive')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 840),
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                child: TextField(
                  decoration: const InputDecoration(
                    hintText: 'Search doctrines',
                    prefixIcon: Icon(Icons.search),
                  ),
                  onChanged: (v) => setState(() => _query = v),
                ),
              ),
              Expanded(
                child: async.when(
                  loading: () => const Center(child: CircularProgressIndicator()),
                  error: (e, _) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text('Could not load the archive.\n$e',
                          textAlign: TextAlign.center),
                    ),
                  ),
                  data: (docs) {
                    final filtered = q.isEmpty
                        ? docs
                        : docs
                            .where((d) =>
                                d.title.toLowerCase().contains(q) ||
                                d.id.toLowerCase().contains(q))
                            .toList();
                    if (filtered.isEmpty) {
                      return const Center(child: Text('No matching documents'));
                    }
                    return ListView.separated(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: filtered.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (_, i) {
                        final d = filtered[i];
                        final busy = _busyId == d.id;
                        return ListTile(
                          leading: const Icon(Icons.picture_as_pdf_outlined),
                          title: Text(d.title,
                              maxLines: 2, overflow: TextOverflow.ellipsis),
                          subtitle: Text(d.id,
                              style: theme.textTheme.bodySmall
                                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
                          trailing: busy
                              ? const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child: CircularProgressIndicator(strokeWidth: 2))
                              : IconButton(
                                  tooltip: 'Download',
                                  icon: const Icon(Icons.download_outlined),
                                  onPressed: () => _open(d, download: true),
                                ),
                          onTap: busy ? null : () => _open(d),
                        );
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
