import 'dart:async';
// ============================================================
// trade_screen.dart — Active Trade Monitor
// Shows current trade state, levels, P&L tracker
// ============================================================

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../services/api_service.dart';

class TradeScreen extends StatefulWidget {
  const TradeScreen({super.key});

  @override
  State<TradeScreen> createState() => _TradeScreenState();
}

class _TradeScreenState extends State<TradeScreen> {
  static const _gold    = Color(0xFFFFD700);
  static const _bg      = Color(0xFF0A0E1A);
  static const _card    = Color(0xFF1A2236);
  static const _bullish = Color(0xFF00C896);
  static const _bearish = Color(0xFFFF4560);

  Map<String, dynamic>? _state;
  Map<String, dynamic>? _price;
  bool _loading = true;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([
        ApiService.getTradeState(),
        ApiService.getPrice(),
      ]);
      if (mounted) {
        setState(() {
          _state   = results[0];
          _price   = results[1];
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _fmt(dynamic p) =>
      p == null ? '—' : NumberFormat('#,##0.00').format((p as num).toDouble());

  double? _unrealisedPips() {
    final state = _state;
    final price = _price;
    if (state == null || price == null) return null;
    if (state['status'] != 'ACTIVE') return null;

    final entry     = (state['entry'] as num?)?.toDouble();
    final bid       = (price['bid']   as num?)?.toDouble();
    final direction = state['direction'] as String?;

    if (entry == null || bid == null || direction == null) return null;

    return direction == 'buy'
        ? (bid - entry) * 10
        : (entry - bid) * 10;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        title: const Text('Trade Monitor'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _load,
            color: Colors.white38,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _gold))
          : ListView(
              padding: const EdgeInsets.only(bottom: 24),
              children: [
                _buildStatusCard(),
                if (_state?['status'] == 'ACTIVE' || _state?['status'] == 'SIGNAL')
                  _buildLevelsCard(),
                _buildRulesCard(),
              ],
            ),
    );
  }

  Widget _buildStatusCard() {
    final s           = _state;
    final status      = s?['status'] ?? 'IDLE';
    final pips        = _unrealisedPips();
    final m1Confirmed = s?['m1_confirmed'] == true;

    Color statusColor = status == 'ACTIVE' ? _bullish
        : status == 'SIGNAL' ? _gold
        : status == 'COOLDOWN' ? Colors.orange
        : Colors.white24;

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 6),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: statusColor.withValues(alpha: 0.3), width: 1.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(children: [
                Container(
                  width: 10, height: 10,
                  decoration: BoxDecoration(
                    color: statusColor,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  status,
                  style: TextStyle(
                    color: statusColor,
                    fontWeight: FontWeight.bold,
                    fontSize: 18,
                    letterSpacing: 0.5,
                  ),
                ),
              ]),
              if (pips != null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(
                    color: (pips >= 0 ? _bullish : _bearish).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                        color: (pips >= 0 ? _bullish : _bearish).withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    '${pips >= 0 ? '+' : ''}${pips.toStringAsFixed(1)} pips',
                    style: TextStyle(
                      color: pips >= 0 ? _bullish : _bearish,
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
                  ),
                ),
            ],
          ),

          if (s?['direction'] != null) ...[
            const SizedBox(height: 14),
            Row(children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                decoration: BoxDecoration(
                  color: (s!['direction'] == 'buy' ? _bullish : _bearish).withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  (s['direction'] as String).toUpperCase(),
                  style: TextStyle(
                    color: s['direction'] == 'buy' ? _bullish : _bearish,
                    fontWeight: FontWeight.bold,
                    fontSize: 14,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              if (s['model'] != null)
                Text(
                  (s['model'] as String).replaceAll('_', ' '),
                  style: TextStyle(color: Colors.white54, fontSize: 13),
                ),
            ]),
          ],

          if (s?['entry_time'] != null) ...[
            const SizedBox(height: 8),
            Text(
              'Entered: ${s!['entry_time']}',
              style: TextStyle(color: Colors.white24, fontSize: 11),
            ),
          ],

          // TP flags
          if (status == 'ACTIVE') ...[
            const SizedBox(height: 12),
            Row(children: [
              _tpFlag('TP1', s?['tp1_hit'] == true),
              const SizedBox(width: 8),
              _tpFlag('TP2', s?['tp2_hit'] == true),
              const SizedBox(width: 8),
              _tpFlag('BE',  s?['sl_at_be'] == true),
              const SizedBox(width: 8),
              _tpFlag('M1 ✓', m1Confirmed),
            ]),
          ],

          // M1 waiting indicator
          if (status == 'SIGNAL') ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: _gold.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _gold.withValues(alpha: 0.25)),
              ),
              child: Row(children: [
                Icon(Icons.candlestick_chart_rounded, size: 13, color: _gold),
                const SizedBox(width: 6),
                Text(
                  m1Confirmed ? 'M1 confirmed ✓' : 'Waiting for M1 rejection candle',
                  style: TextStyle(
                    color: m1Confirmed ? _bullish : _gold,
                    fontSize: 11,
                  ),
                ),
              ]),
            ),
          ],
        ],
      ),
    );
  }

  Widget _tpFlag(String label, bool hit) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: hit ? _bullish.withValues(alpha: 0.2) : Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
          color: hit ? _bullish.withValues(alpha: 0.5) : Colors.white12,
        ),
      ),
      child: Row(children: [
        Icon(
          hit ? Icons.check_circle_rounded : Icons.radio_button_unchecked,
          size: 12,
          color: hit ? _bullish : Colors.white24,
        ),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(color: hit ? _bullish : Colors.white38, fontSize: 11)),
      ]),
    );
  }

  Widget _buildLevelsCard() {
    final s = _state;
    if (s == null) return const SizedBox();

    final bid = (_price?['bid'] as num?)?.toDouble();

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 6),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('LEVELS', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
          const SizedBox(height: 14),

          if (bid != null) ...[
            _levelRow('PRICE NOW', bid, _gold, bold: true),
            const Divider(color: Colors.white12, height: 16),
          ],

          _levelRow('ENTRY',  s['entry']?.toDouble(),  Colors.white70),
          _levelRow('STOP',   s['sl']?.toDouble(),     _bearish),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 4),
            child: Divider(color: Colors.white12, height: 1),
          ),
          _levelRow('TP1 1:1', s['tp1']?.toDouble(),  _bullish),
          _levelRow('TP2 1:2', s['tp2']?.toDouble(),  _bullish),
          _levelRow('TP3 1:3', s['tp3']?.toDouble(),  _gold, bold: true),

          const SizedBox(height: 12),
          if (s['lot_size'] != null)
            Row(children: [
              Icon(Icons.scale_rounded, size: 14, color: Colors.white38),
              const SizedBox(width: 6),
              Text(
                'Lot size: ${s['lot_size']}',
                style: TextStyle(color: Colors.white38, fontSize: 12),
              ),
            ]),
        ],
      ),
    );
  }

  Widget _levelRow(String label, double? price, Color color, {bool bold = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: Colors.white38, fontSize: 12)),
          Text(
            _fmt(price),
            style: TextStyle(
              color: color,
              fontSize: bold ? 16 : 14,
              fontWeight: bold ? FontWeight.bold : FontWeight.w500,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRulesCard() {
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('TRADE RULES', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
          const SizedBox(height: 12),
          _rule('TP1 hit → close 30%, move SL to breakeven'),
          _rule('TP2 hit → close 50% of remainder'),
          _rule('TP3 hit → close everything'),
          _rule('SL hit → 15 minute cooldown'),
          _rule('Never chase entry beyond 50% of SL distance'),
          _rule('One trade active at a time'),
        ],
      ),
    );
  }

  Widget _rule(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Container(
              width: 5, height: 5,
              decoration: BoxDecoration(
                color: _gold.withValues(alpha: 0.6),
                shape: BoxShape.circle,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(text, style: TextStyle(color: Colors.white54, fontSize: 12)),
          ),
        ],
      ),
    );
  }
}