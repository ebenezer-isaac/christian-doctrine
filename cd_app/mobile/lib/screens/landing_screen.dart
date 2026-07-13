import 'dart:async';
import 'dart:ui';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/gsi_button.dart';
import '../services/pdf_opener.dart';
import '../state/providers.dart';
import '../theme/app_theme.dart';

/// Public entry page. The testimony, in first person, then the login gate.
class LandingScreen extends ConsumerStatefulWidget {
  const LandingScreen({super.key});

  @override
  ConsumerState<LandingScreen> createState() => _LandingScreenState();
}

class _LandingScreenState extends ConsumerState<LandingScreen> {
  final _scroll = ScrollController();
  StreamSubscription<GoogleSignInAccount?>? _sub;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final auth = ref.read(authServiceProvider);
    // The web GIS button (and silent restore) surface the account here.
    _sub = auth.onUserChanged.listen((account) async {
      if (await auth.adopt(account) && mounted) {
        ref.read(signedInProvider.notifier).state = true;
      }
    });
    auth.initSilent();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _signIn() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ok = await ref.read(authServiceProvider).signIn();
      if (ok) {
        ref.read(signedInProvider.notifier).state = true;
      } else {
        setState(() => _error = 'Sign-in cancelled.');
      }
    } catch (_) {
      setState(() => _error = 'Could not sign in. Check your connection.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _readStory() {
    if (kIsWeb) {
      // The testimony is on this page on web; scroll to it.
      _scroll.animateTo(
        MediaQuery.of(context).size.height * 0.86,
        duration: const Duration(milliseconds: 700),
        curve: Curves.easeInOutCubic,
      );
    } else {
      // On mobile the testimony lives on the website; open it externally.
      launchUrl(
        Uri.parse('https://christian-doctrine.ebenezer-isaac.com'),
        mode: LaunchMode.externalApplication,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: _GlassNav(
        busy: _busy,
        // On web the GIS button lives in the hero, so the nav just scrolls up.
        onSignIn: kIsWeb
            ? () => _scroll.animateTo(0,
                duration: const Duration(milliseconds: 500), curve: Curves.easeOut)
            : _signIn,
      ),
      body: SingleChildScrollView(
        controller: _scroll,
        child: Column(
          children: [
            _Hero(
              busy: _busy,
              error: _error,
              onSignIn: _signIn,
              onReadStory: _readStory,
            ),
            _Body(scroll: _scroll, onSignIn: _signIn, busy: _busy),
          ],
        ),
      ),
    );
  }
}

// --------------------------------------------------------------------------
// Nav
// --------------------------------------------------------------------------
class _GlassNav extends StatelessWidget implements PreferredSizeWidget {
  const _GlassNav({required this.busy, required this.onSignIn});
  final bool busy;
  final VoidCallback onSignIn;

  @override
  Size get preferredSize => const Size.fromHeight(kToolbarHeight);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // A real AppBar so the status-bar inset is handled automatically (the title
    // sits below the clock/battery on mobile); flexibleSpace carries the blur.
    return AppBar(
      backgroundColor: Colors.transparent,
      elevation: 0,
      titleSpacing: 20,
      flexibleSpace: ClipRect(
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
          child: Container(
            color: theme.scaffoldBackgroundColor.withValues(alpha: 0.55),
          ),
        ),
      ),
      title: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Image.asset('assets/icon/logo.png', width: 30, height: 30),
          const SizedBox(width: 10),
          Text('Christian Doctrine',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600)),
        ],
      ),
      actions: [
        Padding(
          padding: const EdgeInsets.only(right: 10),
          child: TextButton(
            onPressed: busy ? null : onSignIn,
            child: const Text('Sign in'),
          ),
        ),
      ],
    );
  }
}

// --------------------------------------------------------------------------
// Hero
// --------------------------------------------------------------------------
class _Hero extends StatelessWidget {
  const _Hero({
    required this.busy,
    required this.error,
    required this.onSignIn,
    required this.onReadStory,
  });
  final bool busy;
  final String? error;
  final VoidCallback onSignIn;
  final VoidCallback onReadStory;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final size = MediaQuery.of(context).size;
    // Web has no status bar, so keep the top gap small (the medallion sat too
    // low); mobile keeps a comfortable gap below the nav.
    final navClearance =
        MediaQuery.of(context).padding.top + kToolbarHeight + (kIsWeb ? 8.0 : 36.0);

    return Container(
      width: double.infinity,
      child: Stack(
        children: [
          // Background gradient + glows are positioned, so they never inflate
          // the content-driven height (no wasted vertical space).
          Positioned.fill(
            child: Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Color(0xFF141A38), Color(0xFF0B0D12)],
                ),
              ),
            ),
          ),
          Positioned.fill(
            child: _glow(const Alignment(-0.8, -0.7), AppTheme.seed.withValues(alpha: 0.55), 520),
          ),
          Positioned.fill(
            child: _glow(const Alignment(0.9, -0.2), AppTheme.gold.withValues(alpha: 0.16), 420),
          ),
          // Content, top-aligned with clearance below the nav.
          Padding(
            padding: EdgeInsets.only(top: navClearance, bottom: 64, left: 24, right: 24),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _FadeIn(
                      delayMs: 0,
                      child: Image.asset('assets/icon/logo.png', width: 132, height: 132),
                    ),
                    const SizedBox(height: 40),
                    _FadeIn(
                      delayMs: 100,
                      child: Text(
                        'A PERSONAL SEARCH FOR THE TRUTH WORTH DYING FOR',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.labelMedium?.copyWith(
                          color: AppTheme.gold,
                          letterSpacing: 2.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    _FadeIn(
                      delayMs: 180,
                      child: Text(
                        'Christian Doctrine',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.displayMedium?.copyWith(
                          color: Colors.white,
                          fontSize: size.width < 600 ? 44 : 68,
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    _FadeIn(
                      delayMs: 260,
                      child: Text(
                        'Answers anchored to Scripture in the original languages. The verdict '
                        'comes from the manuscript alone. Church Traditions are shown '
                        'alongside as diagnostic, never as judge.',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.titleMedium?.copyWith(
                          color: Colors.white.withValues(alpha: 0.82),
                          height: 1.6,
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                    ),
                    const SizedBox(height: 36),
                    _FadeIn(
                      delayMs: 340,
                      child: Wrap(
                        spacing: 14,
                        runSpacing: 12,
                        alignment: WrapAlignment.center,
                        children: [
                          _HoverButton(
                            busy: busy,
                            onPressed: onSignIn,
                          ),
                          OutlinedButton(
                            onPressed: onReadStory,
                            style: OutlinedButton.styleFrom(
                              foregroundColor: Colors.white,
                              side: BorderSide(color: Colors.white.withValues(alpha: 0.3)),
                              padding:
                                  const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                              shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(30)),
                            ),
                            child: const Text('Read the story'),
                          ),
                        ],
                      ),
                    ),
                    if (kIsWeb) ...[
                      const SizedBox(height: 14),
                      _FadeIn(
                        delayMs: 420,
                        child: TextButton.icon(
                          onPressed: () => openUrl('/christian-doctrine.apk'),
                          icon: const Icon(Icons.android, size: 18, color: Colors.white70),
                          label: const Text('Download the Android app',
                              style: TextStyle(color: Colors.white70)),
                        ),
                      ),
                    ],
                    if (error != null) ...[
                      const SizedBox(height: 16),
                      Text(error!, style: const TextStyle(color: Color(0xFFFFB4A9))),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _glow(Alignment a, Color c, double d) => Align(
        alignment: a,
        child: Container(
          width: d,
          height: d,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: RadialGradient(colors: [c, c.withValues(alpha: 0)]),
          ),
        ),
      );
}

// --------------------------------------------------------------------------
// Body: the testimony
// --------------------------------------------------------------------------
class _Body extends StatelessWidget {
  const _Body({required this.scroll, required this.onSignIn, required this.busy});
  final ScrollController scroll;
  final VoidCallback onSignIn;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 72, 24, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Testimony is public on the web only; the mobile app is the tool.
              if (kIsWeb) ...[
              _Reveal(
                scroll: scroll,
                child: _Prose(
                  eyebrow: 'HOW I GOT HERE',
                  title: 'I have always been a skeptic',
                  paragraphs: const [
                    'I was born into a Christian Brethren family, but my nature has always '
                        'been to doubt. For a long time I was not sure God even existed. I used '
                        'to pray something like: I am willing to forgo the blessing of believing '
                        'without seeing, because reaching heaven with one less blessing seems '
                        'better than going altogether to hell for unbelief. It was Pascal\'s '
                        'Wager dressed up as humility. But I meant it.',
                    'The conviction came in my early twenties. I would sit under a tree and '
                        'think about how the world actually works, and I finally faced something '
                        'obvious: if even one year the trees never came back to life, the whole '
                        'thing collapses. No oxygen, no food chain, nothing. Every life on the '
                        'planet dies. For a system that delicate to run flawlessly for thousands '
                        'of years, someone has to be holding it together from behind. From there '
                        'I was convinced there was a God.',
                    'Then the harder question landed. If God exists, who is God? Was I leaning '
                        'toward Jesus only because I had been raised Christian? I owed the '
                        'question real work, so I read other traditions and spoke with their '
                        'leaders. What I found was that only Christianity held up under every '
                        'question I threw at it, to the point that it began to feel too perfect '
                        'to be true. The God of the Bible and the workings of the world ran on '
                        'the same source code. Watching Lee Strobel\'s Case for Christ put the '
                        'last nail in my old self.',
                  ],
                ),
              ),
              const SizedBox(height: 56),
              _Reveal(
                scroll: scroll,
                child: _Prose(
                  eyebrow: 'THE QUESTION I CANNOT STOP ASKING',
                  title: 'Is my conviction inheritance, or is it verified?',
                  paragraphs: const [
                    'That should have been the end of it. It was not. Back home the answer to '
                        'which church was obvious: Brethren. It is what I was born into, what I '
                        'knew, and the doctrine matched what I was taught. But the same skeptic '
                        'voice that carried me through the first two questions keeps returning.',
                    'It grew louder when I moved to London, where the distinct Brethren churches '
                        'are few and the rest have changed a great deal. I came to Christianity '
                        'because of its singular, unbreakable truth. So why are there so many '
                        'denominations within it? If truth is singular, should there not be a '
                        'singular church?',
                  ],
                ),
              ),
              const SizedBox(height: 48),
              _Reveal(scroll: scroll, child: const _PullQuote()),
              const SizedBox(height: 56),
              _Reveal(scroll: scroll, child: const _Stages()),
              const SizedBox(height: 64),
              ],
              _Reveal(
                scroll: scroll,
                child: _Prose(
                  eyebrow: 'WHAT THIS IS',
                  title: 'A tool for calibrated discernment',
                  paragraphs: const [
                    'This engine produces a doctrinal verdict from the original-language '
                        'manuscript tradition alone, then attaches a diagnostic overlay showing '
                        'how each tracked Christian tradition reads the same lexical pattern. The '
                        'lexical and cultural sources live in two physically separate, '
                        'air-gapped stores, so the verdict is settled by Scripture, not by any '
                        'one church\'s summary.',
                    'The aim is calibrated discernment, not church-scoring. A church that checks '
                        'green on every marker can still fall flat in practice. There is a '
                        'difference between believing a doctrine and living it.',
                  ],
                ),
              ),
              const SizedBox(height: 56),
              _Reveal(scroll: scroll, child: _ClosingCta(busy: busy, onSignIn: onSignIn)),
              const _Footer(),
            ],
          ),
        ),
      ),
    );
  }
}

class _Prose extends StatelessWidget {
  const _Prose({required this.eyebrow, required this.title, required this.paragraphs});
  final String eyebrow;
  final String title;
  final List<String> paragraphs;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(eyebrow,
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.colorScheme.tertiary,
              letterSpacing: 2,
              fontWeight: FontWeight.w600,
            )),
        const SizedBox(height: 12),
        Text(title, style: theme.textTheme.headlineMedium?.copyWith(height: 1.2)),
        const SizedBox(height: 20),
        ...paragraphs.map((p) => Padding(
              padding: const EdgeInsets.only(bottom: 18),
              child: Text(p, style: theme.textTheme.bodyLarge),
            )),
      ],
    );
  }
}

class _PullQuote extends StatelessWidget {
  const _PullQuote();
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.only(left: 24),
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: theme.colorScheme.tertiary, width: 3)),
      ),
      child: Text(
        'This is my attempt to name, for myself, the truths I am willing to lay my '
        'life down for, and the truths I am willing to live and let live.',
        style: theme.textTheme.headlineSmall!.copyWith(
          fontStyle: FontStyle.italic,
          height: 1.4,
          color: theme.colorScheme.onSurface,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }
}

class _Stages extends StatelessWidget {
  const _Stages();
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    const stages = [
      ('1', 'Does God exist?', 'Settled, under that tree.', true),
      ('2', 'Is Jesus God?', 'Settled, after the comparative work and Strobel.', true),
      ('3', 'Which church is right?', 'Open. This engine is how I investigate it.', false),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('THE THREE-STAGE PROGRESSION',
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.colorScheme.tertiary,
              letterSpacing: 2,
              fontWeight: FontWeight.w600,
            )),
        const SizedBox(height: 24),
        for (var i = 0; i < stages.length; i++)
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Column(
                  children: [
                    Container(
                      width: 40,
                      height: 40,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: stages[i].$4
                            ? theme.colorScheme.primary.withValues(alpha: 0.18)
                            : theme.colorScheme.tertiary,
                        border: Border.all(
                          color: stages[i].$4
                              ? theme.colorScheme.primary
                              : theme.colorScheme.tertiary,
                        ),
                      ),
                      child: stages[i].$4
                          ? Icon(Icons.check, size: 20, color: theme.colorScheme.primary)
                          : Text('3',
                              style: TextStyle(
                                  color: Colors.black.withValues(alpha: 0.8),
                                  fontWeight: FontWeight.bold)),
                    ),
                    if (i < stages.length - 1)
                      Expanded(
                        child: Container(
                          width: 2,
                          color: theme.colorScheme.onSurface.withValues(alpha: 0.12),
                        ),
                      ),
                  ],
                ),
                const SizedBox(width: 18),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: 28),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(stages[i].$2, style: theme.textTheme.titleLarge),
                        const SizedBox(height: 4),
                        Text(stages[i].$3,
                            style: theme.textTheme.bodyMedium
                                ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _ClosingCta extends StatelessWidget {
  const _ClosingCta({required this.busy, required this.onSignIn});
  final bool busy;
  final VoidCallback onSignIn;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 44, horizontal: 32),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: LinearGradient(
          colors: [AppTheme.seed.withValues(alpha: 0.22), AppTheme.seed.withValues(alpha: 0.06)],
        ),
        border: Border.all(color: theme.colorScheme.primary.withValues(alpha: 0.25)),
      ),
      child: Column(
        children: [
          Text('Ask a question',
              textAlign: TextAlign.center, style: theme.textTheme.headlineSmall),
          const SizedBox(height: 10),
          Text(
            'Sign in to open the engine and put a doctrine or a verse to the manuscripts.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 24),
          _HoverButton(busy: busy, onPressed: onSignIn),
        ],
      ),
    );
  }
}

class _Footer extends StatelessWidget {
  const _Footer();
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 44),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextButton.icon(
              onPressed: () {
                const gh = 'https://github.com/ebenezer-isaac/christian-doctrine';
                if (kIsWeb) {
                  openUrl(gh);
                } else {
                  launchUrl(Uri.parse(gh), mode: LaunchMode.externalApplication);
                }
              },
              icon: const Icon(Icons.open_in_new, size: 15),
              label: const Text('View source on GitHub'),
            ),
            const SizedBox(height: 6),
            Text('Single-user, personal-use tooling.',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          ],
        ),
      ),
    );
  }
}

// --------------------------------------------------------------------------
// Primitives
// --------------------------------------------------------------------------

/// White pill CTA with a hover lift, works on web + mobile.
class _HoverButton extends StatefulWidget {
  const _HoverButton({required this.busy, required this.onPressed});
  final bool busy;
  final VoidCallback onPressed;

  @override
  State<_HoverButton> createState() => _HoverButtonState();
}

class _HoverButtonState extends State<_HoverButton> {
  bool _hover = false;
  @override
  Widget build(BuildContext context) {
    if (kIsWeb) {
      // Google requires its own rendered button for web sign-in.
      return SizedBox(height: 44, width: 240, child: renderGoogleButton());
    }
    final scheme = Theme.of(context).colorScheme;
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: AnimatedScale(
        scale: _hover ? 1.03 : 1.0,
        duration: const Duration(milliseconds: 150),
        child: FilledButton.icon(
          onPressed: widget.busy ? null : widget.onPressed,
          icon: widget.busy
              ? const SizedBox(
                  width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.login, size: 20),
          label: const Text('Sign in with Google'),
          style: FilledButton.styleFrom(
            backgroundColor: Colors.white,
            foregroundColor: const Color(0xFF1B1E3A),
            padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 17),
          ),
        ),
      ),
    );
  }
}

/// Fade + slide up once its position enters the viewport.
class _Reveal extends StatefulWidget {
  const _Reveal({required this.scroll, required this.child});
  final ScrollController scroll;
  final Widget child;

  @override
  State<_Reveal> createState() => _RevealState();
}

class _RevealState extends State<_Reveal> with SingleTickerProviderStateMixin {
  final _key = GlobalKey();
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 650));
  bool _shown = false;

  @override
  void initState() {
    super.initState();
    widget.scroll.addListener(_check);
    WidgetsBinding.instance.addPostFrameCallback((_) => _check());
  }

  void _check() {
    if (_shown || !mounted) return;
    final ctx = _key.currentContext;
    final box = ctx?.findRenderObject() as RenderBox?;
    if (box == null || !box.hasSize) return;
    final dy = box.localToGlobal(Offset.zero).dy;
    if (dy < MediaQuery.of(context).size.height * 0.9) {
      _shown = true;
      _c.forward();
    }
  }

  @override
  void dispose() {
    widget.scroll.removeListener(_check);
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (_, child) {
        final t = Curves.easeOut.transform(_c.value);
        return Opacity(
          opacity: t,
          child: Transform.translate(offset: Offset(0, (1 - t) * 28), child: child),
        );
      },
      child: KeyedSubtree(key: _key, child: widget.child),
    );
  }
}

/// One-shot fade-in used for staggered hero entrance.
class _FadeIn extends StatefulWidget {
  const _FadeIn({required this.child, required this.delayMs});
  final Widget child;
  final int delayMs;

  @override
  State<_FadeIn> createState() => _FadeInState();
}

class _FadeInState extends State<_FadeIn> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 600));

  @override
  void initState() {
    super.initState();
    Future.delayed(Duration(milliseconds: widget.delayMs), () {
      if (mounted) _c.forward();
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (_, child) {
        final t = Curves.easeOut.transform(_c.value);
        return Opacity(
          opacity: t,
          child: Transform.translate(offset: Offset(0, (1 - t) * 18), child: child),
        );
      },
      child: widget.child,
    );
  }
}
