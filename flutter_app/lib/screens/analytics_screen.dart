// ============================================================
// analytics_screen.dart — Performance Analytics
// Winrate, pips, model breakdown, recent trades
// ============================================================

import 'package:flutter/material.dart';
import '../services/api_service.dart';

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  static const _gold    = Color(0xFFFFD700);
  static const _bg      = Color(0xFF0A0E1A);
  static const _card    = Color(0xFF1A2236);
  static const _bullish = Color(0xFF00C896);
  static const _bearish = Color(0xFFFF4560);

  Map<String, dynamic>? _analytics;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _error = null; });
    try {
      final data = await ApiService.getAnalytics();
      setState(() { _analytics = data; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        title: const Text('Analytics'),
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
          : _error != null
              ? Center(child: Text(_error!, style: const TextStyle(color: Colors.white38)))
              : RefreshIndicator(
                  color: _gold,
                  backgroundColor: _card,
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.only(bottom: 24),
                    children: [
                      _buildHealthCard(),
                      _buildStatsCard('30 DAY PERFORMANCE', _analytics?['stats_30d']),
                      _buildStatsCard('7 DAY PERFORMANCE',  _analytics?['stats_7d']),
                      _buildTodayCard(),
                      _buildModelStatsCard(),
                      _buildRecentTradesCard(),
                    ],
                  ),
                ),
    );
  }

  Widget _buildHealthCard() {
    final health = (_analytics?['health_score'] ?? 100).toDouble();
    final color  = health >= 70 ? _bullish : health >= 40 ? _gold : _bearish;

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 6),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.3), width: 1.5),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 64, height: 64,
            child: Stack(
              alignment: Alignment.center,
              children: [
                CircularProgressIndicator(
                  value: health / 100,
                  backgroundColor: Colors.white10,
                  valueColor: AlwaysStoppedAnimation(color),
                  strokeWidth: 5,
                ),
                Text(
                  '${health.toInt()}',
                  style: TextStyle(
                    color: color,
                    fontWeight: FontWeight.bold,
                    fontSize: 18,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 20),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('SYSTEM HEALTH', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1)),
              const SizedBox(height: 4),
              Text(
                health >= 70 ? 'Healthy' : health >= 40 ? 'Caution' : 'Review Needed',
                style: TextStyle(color: color, fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 2),
              Text(
                'Based on recent performance',
                style: TextStyle(color: Colors.white24, fontSize: 11),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatsCard(String title, Map<String, dynamic>? stats) {
    if (stats == null) return const SizedBox();

    final total   = stats['total_trades'] ?? 0;
    final wins    = stats['wins']         ?? 0;
    final losses  = stats['losses']       ?? 0;
    final winrate = (stats['winrate']     ?? 0).toDouble();
    final pips    = (stats['total_pips']  ?? 0).toDouble();
    final pf      = (stats['profit_factor'] ?? 0).toDouble();
    final rr      = (stats['avg_rr']      ?? 0).toDouble();
    final best    = (stats['best_trade_pips']  ?? 0).toDouble();
    final worst   = (stats['worst_trade_pips'] ?? 0).toDouble();

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
          Text(title, style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
          const SizedBox(height: 16),

          if (total == 0)
            Center(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  'No trades yet',
                  style: TextStyle(color: Colors.white24, fontSize: 13),
                ),
              ),
            )
          else ...[
            // Win/Loss bar
            Row(children: [
              Expanded(
                flex: wins > 0 ? wins : 1,
                child: Container(
                  height: 6,
                  decoration: BoxDecoration(
                    color: _bullish,
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
              ),
              const SizedBox(width: 2),
              Expanded(
                flex: losses > 0 ? losses : 1,
                child: Container(
                  height: 6,
                  decoration: BoxDecoration(
                    color: _bearish,
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
              ),
            ]),
            const SizedBox(height: 12),

            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _bigStat('$total', 'TRADES', Colors.white70),
                _bigStat('${winrate.toStringAsFixed(0)}%', 'WINRATE',
                    winrate >= 55 ? _bullish : winrate >= 45 ? _gold : _bearish),
                _bigStat('${pips >= 0 ? '+' : ''}${pips.toStringAsFixed(0)}', 'PIPS',
                    pips >= 0 ? _bullish : _bearish),
              ],
            ),
            const SizedBox(height: 14),
            Divider(color: Colors.white.withValues(alpha: 0.08), height: 1),
            const SizedBox(height: 14),

            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _smallStat('W/L', '$wins / $losses'),
                _smallStat('Profit Factor', pf.toStringAsFixed(2)),
                _smallStat('Avg RR', rr.toStringAsFixed(2)),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _smallStat('Best Trade', '+${best.toStringAsFixed(1)} pips'),
                _smallStat('Worst Trade', '${worst.toStringAsFixed(1)} pips'),
                _smallStat('Max Loss Streak', '${stats['max_loss_streak']}'),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildTodayCard() {
    final today = _analytics?['today'] as Map?;
    if (today == null) return const SizedBox();

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
          Text('TODAY', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
          const SizedBox(height: 12),
          if ((today['total_trades'] ?? 0) == 0)
            Text('No trades today', style: TextStyle(color: Colors.white24, fontSize: 13))
          else
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _bigStat('${today['total_trades']}', 'TRADES', Colors.white70),
                _bigStat('${today['wins']}W / ${today['losses']}L', 'RECORD', Colors.white70),
                _bigStat(
                  '${(today['total_pips'] ?? 0) >= 0 ? '+' : ''}${(today['total_pips'] ?? 0).toStringAsFixed(1)}',
                  'PIPS',
                  (today['total_pips'] ?? 0) >= 0 ? _bullish : _bearish,
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _buildModelStatsCard() {
    final stats = _analytics?['stats_30d'];
    final modelStats = stats?['model_stats'] as Map?;
    if (modelStats == null || modelStats.isEmpty) return const SizedBox();

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
          Text('MODEL PERFORMANCE', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
          const SizedBox(height: 12),
          ...modelStats.entries.map((e) {
            final m       = e.value as Map;
            final trades  = m['trades']  ?? 0;
            final winrate = (m['winrate'] ?? 0).toDouble();
            final pips    = (m['pips']    ?? 0).toDouble();
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(children: [
                Expanded(
                  child: Text(
                    e.key.toString().replaceAll('_', ' '),
                    style: TextStyle(color: Colors.white54, fontSize: 12),
                  ),
                ),
                Text('$trades trades', style: TextStyle(color: Colors.white24, fontSize: 11)),
                const SizedBox(width: 10),
                Text(
                  '${winrate.toStringAsFixed(0)}%',
                  style: TextStyle(
                    color: winrate >= 55 ? _bullish : winrate >= 45 ? _gold : _bearish,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  '${pips >= 0 ? '+' : ''}${pips.toStringAsFixed(0)}p',
                  style: TextStyle(
                    color: pips >= 0 ? _bullish : _bearish,
                    fontSize: 11,
                  ),
                ),
              ]),
            );
          }),
        ],
      ),
    );
  }

  Widget _buildRecentTradesCard() {
    final stats  = _analytics?['stats_30d'];
    final trades = stats?['recent_trades'] as List?;
    if (trades == null || trades.isEmpty) return const SizedBox();

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
          Text('RECENT TRADES', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
          const SizedBox(height: 12),
          ...trades.take(8).map((t) {
            final pips = (t['pnl_pips'] ?? 0).toDouble();
            final dir  = t['direction'] ?? '';
            final won  = pips > 2;

            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(children: [
                Container(
                  width: 28, height: 28,
                  decoration: BoxDecoration(
                    color: (dir == 'buy' ? _bullish : _bearish).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Center(
                    child: Text(
                      dir == 'buy' ? '↑' : '↓',
                      style: TextStyle(
                        color: dir == 'buy' ? _bullish : _bearish,
                        fontWeight: FontWeight.bold,
                        fontSize: 14,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        (t['model_name'] ?? '').toString().replaceAll('_', ' '),
                        style: TextStyle(color: Colors.white54, fontSize: 11),
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        t['close_reason'] ?? '',
                        style: TextStyle(color: Colors.white24, fontSize: 10),
                      ),
                    ],
                  ),
                ),
                Text(
                  '${pips >= 0 ? '+' : ''}${pips.toStringAsFixed(1)} pips',
                  style: TextStyle(
                    color: won ? _bullish : _bearish,
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                  ),
                ),
              ]),
            );
          }),
        ],
      ),
    );
  }

  Widget _bigStat(String value, String label, Color color) {
    return Column(children: [
      Text(value, style: TextStyle(color: color, fontSize: 22, fontWeight: FontWeight.bold)),
      const SizedBox(height: 3),
      Text(label, style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 0.8)),
    ]);
  }

  Widget _smallStat(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(value, style: const TextStyle(color: Colors.white70, fontSize: 13, fontWeight: FontWeight.w500)),
        Text(label, style: TextStyle(color: Colors.white24, fontSize: 10)),
      ],
    );
  }
}