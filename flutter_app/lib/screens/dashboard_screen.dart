import 'dart:async';
// ============================================================
// dashboard_screen.dart — Signal Dashboard
// Main screen: live price, signal card, trade levels
// Auto-refreshes every 60 seconds
// ============================================================

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../services/api_service.dart';
import 'package:http/http.dart' as http;
import '../models/signal_model.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  // Colors
  static const _gold    = Color(0xFFFFD700);
  static const _bg      = Color(0xFF0A0E1A);
  static const _card    = Color(0xFF1A2236);
  static const _bullish = Color(0xFF00C896);
  static const _bearish = Color(0xFFFF4560);
  static const _neutral = Color(0xFF8892A4);

  SignalModel? _signal;
  PriceModel?  _price;
  bool _loading  = true;
  bool _refreshing = false;
  String? _error;
  Timer? _timer;
  DateTime? _lastUpdate;

  @override
  void initState() {
    super.initState();
    _loadAll();
    // Auto-refresh every 60 seconds
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => _loadAll());
    // Price refresh every 5 seconds
    Timer.periodic(const Duration(seconds: 5), (_) => _loadPrice());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadAll() async {
    setState(() { _refreshing = true; _error = null; });
    try {
      final results = await Future.wait([
        ApiService.getSignal(),
        ApiService.getPrice(),
      ]);
      setState(() {
        _signal     = SignalModel.fromJson(results[0]);
        _price      = PriceModel.fromJson(results[1]);
        _loading    = false;
        _refreshing = false;
        _lastUpdate = DateTime.now();
      });
    } catch (e) {
      setState(() {
        _error      = e.toString();
        _loading    = false;
        _refreshing = false;
      });
    }
  }

  Future<void> _loadPrice() async {
    try {
      final p = await ApiService.getPrice();
      if (mounted) setState(() => _price = PriceModel.fromJson(p));
    } catch (_) {}
  }

  // ------------------------------------------------------------
  // HELPERS
  // ------------------------------------------------------------

  Color _directionColor(String? dir) {
    if (dir == 'buy')  return _bullish;
    if (dir == 'sell') return _bearish;
    return _neutral;
  }

  Color _gradeColor(String grade) {
    switch (grade) {
      case 'STRONG':   return _bullish;
      case 'MODERATE': return _gold;
      case 'WEAK':     return Colors.orange;
      default:         return _neutral;
    }
  }

  String _formatPrice(double? p) =>
      p == null ? '—' : NumberFormat('#,##0.00').format(p);

  String _formatTime(DateTime? t) =>
      t == null ? '—' : DateFormat('HH:mm:ss').format(t);

  // ------------------------------------------------------------
  // BUILD
  // ------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        title: Row(children: [
          Container(
            width: 8, height: 8,
            decoration: BoxDecoration(
              color: _error == null ? _bullish : _bearish,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          const Text('XAUUSD'),
          const SizedBox(width: 6),
          Text(
            '/ GOLD',
            style: TextStyle(
              color: _gold,
              fontSize: 14,
              fontWeight: FontWeight.w500,
            ),
          ),
        ]),
        actions: [
          if (_refreshing)
            const Padding(
              padding: EdgeInsets.all(16),
              child: SizedBox(
                width: 18, height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white38,
                ),
              ),
            )
          else
            IconButton(
              icon: const Icon(Icons.refresh_rounded),
              onPressed: _loadAll,
              color: Colors.white38,
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _gold))
          : _error != null
              ? _buildError()
              : RefreshIndicator(
                  color: _gold,
                  backgroundColor: _card,
                  onRefresh: _loadAll,
                  child: ListView(
                    padding: const EdgeInsets.only(bottom: 24),
                    children: [
                      _buildPriceTicker(),
                      _buildSignalCard(),
                      if (_signal?.shouldTrade == true) _buildLevelsCard(),
                      _buildContextCard(),
                      _buildSentimentCard(),
                      _buildLastUpdate(),
                    ],
                  ),
                ),
    );
  }

  // ------------------------------------------------------------
  // PRICE TICKER
  // ------------------------------------------------------------

  Widget _buildPriceTicker() {
    final p = _price;
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _gold.withValues(alpha: 0.2), width: 1),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('BID', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1)),
            const SizedBox(height: 2),
            Text(
              _formatPrice(p?.bid),
              style: const TextStyle(
                color: _bullish,
                fontSize: 26,
                fontWeight: FontWeight.bold,
                fontFeatures: [FontFeature.tabularFigures()],
              ),
            ),
          ]),
          Column(children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.06),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                p != null ? '${p.spread.toStringAsFixed(1)} pip' : '—',
                style: TextStyle(color: Colors.white54, fontSize: 12),
              ),
            ),
            const SizedBox(height: 4),
            Text('SPREAD', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 1)),
          ]),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('ASK', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1)),
            const SizedBox(height: 2),
            Text(
              _formatPrice(p?.ask),
              style: const TextStyle(
                color: _bearish,
                fontSize: 26,
                fontWeight: FontWeight.bold,
                fontFeatures: [FontFeature.tabularFigures()],
              ),
            ),
          ]),
        ],
      ),
    );
  }

  // ------------------------------------------------------------
  // SIGNAL CARD
  // ------------------------------------------------------------

  Widget _buildSignalCard() {
    final s = _signal;
    if (s == null) return const SizedBox();

    final dirColor = _directionColor(s.direction);
    final gradeColor = _gradeColor(s.grade);

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 4),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: s.shouldTrade ? dirColor.withValues(alpha: 0.4) : Colors.white12,
          width: 1.5,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header row
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(children: [
                // Only show BUY/SELL badge when there is an actual signal
                if (s.shouldTrade) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: dirColor.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: dirColor.withValues(alpha: 0.4)),
                    ),
                    child: Text(
                      s.direction.toUpperCase(),
                      style: TextStyle(
                        color: dirColor,
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                        letterSpacing: 1,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                ],
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: gradeColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    s.grade,
                    style: TextStyle(
                      color: gradeColor,
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                ),
              ]),
              // Score circle + frozen indicator
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Container(
                  width: 52, height: 52,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(color: gradeColor.withValues(alpha: 0.5), width: 2),
                  ),
                  child: Center(
                    child: Text(
                      s.score.toStringAsFixed(0),
                      style: TextStyle(
                        color: gradeColor,
                        fontWeight: FontWeight.bold,
                        fontSize: 17,
                      ),
                    ),
                  ),
                ),
                if (s.scoreFrozen) ...[
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: _gold.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(color: _gold.withValues(alpha: 0.4)),
                    ),
                    child: Text(
                      'FROZEN',
                      style: TextStyle(color: _gold, fontSize: 9, letterSpacing: 0.8),
                    ),
                  ),
                ],
              ]),
            ],
          ),

          const SizedBox(height: 14),

          // Model — breakout models get special label + icon
          if (s.modelName != null) ...[
            Row(children: [
              Icon(
                (s.modelName == 'momentum_breakout' || s.modelName == 'structural_breakout')
                    ? Icons.bolt_rounded
                    : Icons.auto_awesome,
                size: 14,
                color: (s.modelName == 'momentum_breakout' || s.modelName == 'structural_breakout')
                    ? Colors.orange
                    : _gold,
              ),
              const SizedBox(width: 6),
              Text(
                s.modelName!.replaceAll('_', ' ').toUpperCase(),
                style: TextStyle(
                  color: (s.modelName == 'momentum_breakout' || s.modelName == 'structural_breakout')
                      ? Colors.orange
                      : _gold,
                  fontSize: 12,
                  letterSpacing: 0.8,
                  fontWeight: FontWeight.w600,
                ),
              ),
              if (s.modelName == 'momentum_breakout') ...[
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.orange.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: Colors.orange.withValues(alpha: 0.4)),
                  ),
                  child: Text('STRAIGHT SHOOTER', style: TextStyle(color: Colors.orange, fontSize: 9, letterSpacing: 0.6)),
                ),
              ],
              if (s.modelName == 'structural_breakout') ...[
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.orange.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: Colors.orange.withValues(alpha: 0.4)),
                  ),
                  child: Text('BOS RETEST', style: TextStyle(color: Colors.orange, fontSize: 9, letterSpacing: 0.6)),
                ),
              ],
              if (!s.scoreFrozen) ...[const SizedBox(width: 8), Text('${s.validatedCount}/13 models', style: TextStyle(color: Colors.white38, fontSize: 11))],
            ]),
            const SizedBox(height: 10),
          ],

          // Status — hide stale signal message when shouldTrade is false
          Row(children: [
            _statusDot(s.shouldTrade ? s.tradeStatus : 'IDLE'),
            const SizedBox(width: 6),
            Text(
              s.shouldTrade ? s.tradeStatus : 'IDLE',
              style: TextStyle(
                color: _statusColor(s.shouldTrade ? s.tradeStatus : 'IDLE'),
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                s.shouldTrade ? s.stateMessage : 'Scanning — no setup found',
                style: TextStyle(color: Colors.white38, fontSize: 12),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ]),

          // Unlock button — only show when not actively in trade
          if (s.scoreFrozen && s.tradeStatus != 'ACTIVE') ...[
            const SizedBox(height: 10),
            GestureDetector(
              onTap: () async {
                try {
                  final response = await http.post(Uri.parse('http://localhost:8000/trade/unlock'));
                  if (response.statusCode == 200) _loadAll();
                } catch (_) {}
              },
              child: Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.04),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.white12),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.lock_open_rounded, color: Colors.white38, size: 14),
                    const SizedBox(width: 6),
                    Text('Mark trade as closed', style: TextStyle(color: Colors.white38, fontSize: 12)),
                  ],
                ),
              ),
            ),
          ],

          // Blocked reason
          if (s.blocked && s.blockedReason != null) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: _bearish.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _bearish.withValues(alpha: 0.3)),
              ),
              child: Row(children: [
                Icon(Icons.block, color: _bearish, size: 14),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    s.blockedReason!,
                    style: TextStyle(color: _bearish, fontSize: 12),
                  ),
                ),
              ]),
            ),
          ],

          // News warning — only show when blocked OR within 30 mins
          if (s.nextNews != null && s.minutesToNews != null &&
              (s.newsBlocked || s.minutesToNews! <= 30)) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: (s.newsBlocked ? _bearish : Colors.orange).withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: (s.newsBlocked ? _bearish : Colors.orange).withValues(alpha: 0.25)),
              ),
              child: Row(children: [
                Icon(s.newsBlocked ? Icons.block : Icons.schedule,
                    color: s.newsBlocked ? _bearish : Colors.orange, size: 14),
                const SizedBox(width: 8),
                Text(
                  s.newsBlocked
                      ? 'BLOCKED: ${s.blockedReason ?? s.nextNews}'
                      : '${s.minutesToNews!.toInt()}min — ${s.nextNews}',
                  style: TextStyle(
                    color: s.newsBlocked ? _bearish : Colors.orange.shade300,
                    fontSize: 12,
                  ),
                ),
              ]),
            ),
          ],
        ],
      ),
    );
  }

  Widget _statusDot(String status) {
    return Container(
      width: 8, height: 8,
      decoration: BoxDecoration(
        color: _statusColor(status),
        shape: BoxShape.circle,
      ),
    );
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'ACTIVE':   return _bullish;
      case 'SIGNAL':   return _gold;
      case 'COOLDOWN': return Colors.orange;
      case 'CLOSED':   return _neutral;
      default:         return Colors.white24;
    }
  }

  // ------------------------------------------------------------
  // TRADE LEVELS CARD
  // ------------------------------------------------------------

  Widget _buildLevelsCard() {
    final s = _signal;
    if (s == null || s.entry == null) return const SizedBox();

    final dirColor = _directionColor(s.direction);

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.layers_rounded, size: 16, color: dirColor),
            const SizedBox(width: 8),
            Text(
              'TRADE LEVELS',
              style: TextStyle(
                color: Colors.white54,
                fontSize: 11,
                letterSpacing: 1.2,
                fontWeight: FontWeight.w600,
              ),
            ),
            if (s.entryZone != null) ...[
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: dirColor.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  s.entryZone!,
                  style: TextStyle(color: dirColor, fontSize: 11),
                ),
              ),
            ],
          ]),
          const SizedBox(height: 16),

          _levelRow('ENTRY',  s.entry,  dirColor,    Icons.arrow_right_alt),
          const SizedBox(height: 2),
          _levelRow('STOP',   s.sl,     _bearish,    Icons.stop_circle_outlined,
              sub: s.slPips != null ? '${s.slPips!.toStringAsFixed(1)} pips' : null),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Divider(color: Colors.white12, height: 1),
          ),
          _levelRow('TP 1:1', s.tp1,    _bullish,    Icons.flag_outlined),
          const SizedBox(height: 6),
          _levelRow('TP 1:2', s.tp2,    _bullish,    Icons.flag_rounded,  dim: false),
          const SizedBox(height: 6),
          _levelRow('TP 1:3', s.tp3,    _gold,       Icons.flag_rounded,  bold: true),

          const SizedBox(height: 16),

          // Lot size row
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.04),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _statChip('LOT SIZE', s.lotSize?.toStringAsFixed(2) ?? '—', dirColor),
                _statChip('SESSION', s.session.toUpperCase(), Colors.white54),
                _statChip('VOLATILITY', s.volatility.toUpperCase(), Colors.white54),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _levelRow(String label, double? price, Color color, IconData icon,
      {String? sub, bool dim = true, bool bold = false}) {
    return Row(
      children: [
        Icon(icon, size: 16, color: color.withValues(alpha: dim ? 0.7 : 1.0)),
        const SizedBox(width: 10),
        SizedBox(
          width: 58,
          child: Text(
            label,
            style: TextStyle(
              color: Colors.white38,
              fontSize: 12,
              letterSpacing: 0.5,
            ),
          ),
        ),
        Text(
          _formatPrice(price),
          style: TextStyle(
            color: color,
            fontSize: bold ? 17 : 15,
            fontWeight: bold ? FontWeight.bold : FontWeight.w600,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
        if (sub != null) ...[
          const SizedBox(width: 8),
          Text(sub, style: TextStyle(color: Colors.white24, fontSize: 11)),
        ],
      ],
    );
  }

  Widget _statChip(String label, String value, Color color) {
    return Column(children: [
      Text(value, style: TextStyle(color: color, fontSize: 13, fontWeight: FontWeight.w600)),
      const SizedBox(height: 2),
      Text(label, style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 0.8)),
    ]);
  }

  // ------------------------------------------------------------
  // CONTEXT CARD
  // ------------------------------------------------------------

  Widget _buildContextCard() {
    final s = _signal;
    if (s == null) return const SizedBox();

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('MARKET CONTEXT', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
          const SizedBox(height: 14),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _contextItem('HEALTH', '${s.healthScore.toInt()}%',
                  s.healthScore > 70 ? _bullish : s.healthScore > 40 ? _gold : _bearish),
              _contextItem('ATR', s.atr?.toStringAsFixed(1) ?? '—', Colors.white70),
              _contextItem('COT', '${s.cotLongPct?.toStringAsFixed(0) ?? '—'}% L',
                  s.cotSentiment == 'bullish' ? _bullish : s.cotSentiment == 'bearish' ? _bearish : _neutral),
            ],
          ),
        ],
      ),
    );
  }

  Widget _contextItem(String label, String value, Color color) {
    return Column(children: [
      Text(value, style: TextStyle(color: color, fontSize: 15, fontWeight: FontWeight.bold)),
      const SizedBox(height: 3),
      Text(label, style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 0.8)),
    ]);
  }

  // ------------------------------------------------------------
  // SENTIMENT CARD
  // ------------------------------------------------------------

  Widget _buildSentimentCard() {
    final s = _signal;
    if (s == null) return const SizedBox();

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Icon(Icons.people_alt_rounded, size: 16, color: Colors.white38),
          const SizedBox(width: 10),
          Text('COT SENTIMENT', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1)),
          const Spacer(),
          Text(
            s.cotSentiment.toUpperCase(),
            style: TextStyle(
              color: s.cotSentiment == 'bullish' ? _bullish : s.cotSentiment == 'bearish' ? _bearish : _neutral,
              fontWeight: FontWeight.bold,
              fontSize: 13,
            ),
          ),
          const SizedBox(width: 10),
          Text(
            '${s.cotLongPct?.toStringAsFixed(1) ?? '—'}% long',
            style: TextStyle(color: Colors.white38, fontSize: 12),
          ),
        ],
      ),
    );
  }

  // ------------------------------------------------------------
  // LAST UPDATE
  // ------------------------------------------------------------

  Widget _buildLastUpdate() {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Center(
        child: Text(
          'Last update: ${_formatTime(_lastUpdate)}  •  Auto-refresh every 60s',
          style: TextStyle(color: Colors.white24, fontSize: 11),
        ),
      ),
    );
  }

  // ------------------------------------------------------------
  // ERROR
  // ------------------------------------------------------------

  Widget _buildError() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.wifi_off_rounded, color: _bearish, size: 48),
            const SizedBox(height: 16),
            Text(
              'Cannot connect to backend',
              style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text(
              'Make sure python run.py is running',
              style: TextStyle(color: Colors.white38, fontSize: 13),
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              onPressed: _loadAll,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
              style: ElevatedButton.styleFrom(
                backgroundColor: _gold,
                foregroundColor: Colors.black,
              ),
            ),
          ],
        ),
      ),
    );
  }
}