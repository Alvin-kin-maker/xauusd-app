import 'dart:async';
// ============================================================
// market_screen.dart — Market Analysis
// Shows all engine scores and market breakdown
// ============================================================

import 'package:flutter/material.dart';
import '../services/api_service.dart';

class MarketScreen extends StatefulWidget {
  const MarketScreen({super.key});

  @override
  State<MarketScreen> createState() => _MarketScreenState();
}

class _MarketScreenState extends State<MarketScreen> {
  static const _gold    = Color(0xFFFFD700);
  static const _bg      = Color(0xFF0A0E1A);
  static const _card    = Color(0xFF1A2236);
  static const _bullish = Color(0xFF00C896);
  static const _bearish = Color(0xFFFF4560);

  Map<String, dynamic>? _market;
  bool _loading = true;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() { _error = null; });
    try {
      final data = await ApiService.getMarket();
      setState(() { _market = data; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Color _biasColor(String? bias) {
    if (bias == 'bullish') return _bullish;
    if (bias == 'bearish') return _bearish;
    return Colors.white38;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        title: const Text('Market Analysis'),
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
                      _buildConfluenceCard(),
                      _buildTrendCard(),
                      _buildLiquidityCard(),
                      _buildLevelsCard(),
                      _buildFibsCard(),
                      _buildMomentumCard(),
                      _buildEntryCard(),
                      _buildModelsCard(),
                      _buildNewsCard(),
                    ],
                  ),
                ),
    );
  }

  // ------------------------------------------------------------
  // CONFLUENCE OVERVIEW
  // ------------------------------------------------------------

  Widget _buildConfluenceCard() {
    final c = _market?['confluence'];
    final t = _market?['trend'];
    if (c == null) return const SizedBox();

    final score     = (c['score'] ?? 0).toDouble();
    final grade     = c['grade']  ?? 'NO_TRADE';
    final engines   = c['engines'] as Map? ?? {};

    // Use dominant HTF bias (D1 + H4 weighted) instead of confluence direction
    // This is stable and reflects the actual market direction, not a noisy signal
    final overallBias  = t?['overall_bias']  ?? 'neutral';
    final d1Bias       = t?['timeframes']?['D1']?['bias'] ?? 'neutral';
    final h4Bias       = t?['timeframes']?['H4']?['bias'] ?? 'neutral';

    // Dominant = D1 if not neutral, else H4, else overall
    String dominantBias = 'neutral';
    if (d1Bias != 'neutral') {
      dominantBias = d1Bias;
    } else if (h4Bias != 'neutral') {
      dominantBias = h4Bias;
    } else {
      dominantBias = overallBias;
    }

    Color gradeColor = grade == 'STRONG' ? _bullish
        : grade == 'MODERATE' ? _gold
        : grade == 'WEAK' ? Colors.orange
        : Colors.white24;

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 6),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: gradeColor.withValues(alpha: 0.3), width: 1.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('CONFLUENCE', style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
              Row(children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: _biasColor(dominantBias).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    dominantBias.toUpperCase(),
                    style: TextStyle(color: _biasColor(dominantBias), fontWeight: FontWeight.bold, fontSize: 13),
                  ),
                ),
                const SizedBox(width: 8),
                Text(grade, style: TextStyle(color: gradeColor, fontWeight: FontWeight.bold, fontSize: 13)),
              ]),
            ],
          ),
          const SizedBox(height: 16),

          // Score bar
          Row(children: [
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: score / 100,
                  backgroundColor: Colors.white10,
                  valueColor: AlwaysStoppedAnimation(gradeColor),
                  minHeight: 8,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Text(
              '${score.toStringAsFixed(1)}',
              style: TextStyle(color: gradeColor, fontWeight: FontWeight.bold, fontSize: 18),
            ),
          ]),
          const SizedBox(height: 16),

          // Engine contributions
          ...engines.entries.map((e) {
            final contribution = (e.value['contribution'] ?? 0).toDouble();
            final raw          = (e.value['raw']          ?? 0).toDouble();
            return Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(children: [
                SizedBox(
                  width: 110,
                  child: Text(
                    e.key.replaceAll('_', ' '),
                    style: TextStyle(color: Colors.white54, fontSize: 11),
                  ),
                ),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(3),
                    child: LinearProgressIndicator(
                      value: raw / 100,
                      backgroundColor: Colors.white.withValues(alpha: 0.08),
                      valueColor: AlwaysStoppedAnimation(
                        raw >= 70 ? _bullish : raw >= 40 ? _gold : Colors.white24,
                      ),
                      minHeight: 5,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 36,
                  child: Text(
                    '${contribution.toStringAsFixed(1)}',
                    style: TextStyle(color: Colors.white38, fontSize: 11),
                    textAlign: TextAlign.right,
                  ),
                ),
              ]),
            );
          }),
        ],
      ),
    );
  }

  // ------------------------------------------------------------
  // TREND
  // ------------------------------------------------------------

  Widget _buildTrendCard() {
    final t = _market?['trend'];
    if (t == null) return const SizedBox();

    final timeframes = t['timeframes'] as Map? ?? {};
    final tfOrder = ['MN', 'W1', 'D1', 'H4', 'H1', 'M15', 'M5'];
    final mssM15 = t['mss_m15_active'] == true;
    final mssM5  = t['mss_m5_active']  == true;

    return _buildCard('TREND', t['score'], [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text('Overall: ', style: TextStyle(color: Colors.white38, fontSize: 13)),
        Text((t['overall_bias'] ?? 'neutral').toUpperCase(),
            style: TextStyle(color: _biasColor(t['overall_bias']),
                fontWeight: FontWeight.bold, fontSize: 14)),
      ]),
      const SizedBox(height: 6),
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text('External (H4+): ', style: TextStyle(color: Colors.white38, fontSize: 12)),
        Text((t['external_bias'] ?? 'neutral').toUpperCase(),
            style: TextStyle(color: _biasColor(t['external_bias']), fontSize: 12, fontWeight: FontWeight.w600)),
      ]),
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text('Internal (M15): ', style: TextStyle(color: Colors.white38, fontSize: 12)),
        Text((t['internal_bias'] ?? 'neutral').toUpperCase(),
            style: TextStyle(color: _biasColor(t['internal_bias']), fontSize: 12, fontWeight: FontWeight.w600)),
      ]),
      if (mssM15 || mssM5) ...[
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: _gold.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: _gold.withValues(alpha: 0.3)),
          ),
          child: Row(children: [
            Icon(Icons.bolt, color: _gold, size: 14),
            const SizedBox(width: 6),
            Text(
              'MSS ACTIVE${mssM15 ? ' — M15 (${t['mss_m15_type'] ?? ''})' : ''}${mssM5 ? ' — M5 (${t['mss_m5_type'] ?? ''})' : ''}',
              style: TextStyle(color: _gold, fontSize: 11, fontWeight: FontWeight.w600),
            ),
          ]),
        ),
      ],
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: tfOrder.map((tf) {
          final data = timeframes[tf] as Map?;
          if (data == null) return const SizedBox();
          final bias      = data['bias'] ?? 'neutral';
          final mssActive = data['mss_active'] == true;
          final structType = data['structure_type'] ?? 'internal';
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: _biasColor(bias).withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: mssActive ? _gold.withValues(alpha: 0.6) : _biasColor(bias).withValues(alpha: 0.3),
                width: mssActive ? 1.5 : 1.0,
              ),
            ),
            child: Column(children: [
              Text(tf, style: TextStyle(color: Colors.white38, fontSize: 10, letterSpacing: 0.8)),
              const SizedBox(height: 2),
              Text(bias, style: TextStyle(color: _biasColor(bias), fontSize: 11, fontWeight: FontWeight.w600)),
              Text(structType == 'external' ? 'EXT' : 'INT',
                  style: TextStyle(color: Colors.white24, fontSize: 9)),
            ]),
          );
        }).toList(),
      ),
    ]);
  }

  // ------------------------------------------------------------
  // LIQUIDITY
  // ------------------------------------------------------------

  Widget _buildLiquidityCard() {
    final l = _market?['liquidity'];
    if (l == null) return const SizedBox();

    return _buildCard('LIQUIDITY', l['score'], [
      _infoRow('EQH', '${l['eqh_count']}', l['eqh_count'] > 0 ? _gold : Colors.white38),
      _infoRow('EQL', '${l['eql_count']}', l['eql_count'] > 0 ? _gold : Colors.white38),
      _infoRow('PDH Swept', l['pdh_swept'] == true ? 'YES' : 'NO',
          l['pdh_swept'] == true ? _bearish : Colors.white38),
      _infoRow('PDL Swept', l['pdl_swept'] == true ? 'YES' : 'NO',
          l['pdl_swept'] == true ? _bullish : Colors.white38),
      _infoRow('Asian H Swept', l['asian_high_swept'] == true ? 'YES' : 'NO',
          l['asian_high_swept'] == true ? _bearish : Colors.white38),
      _infoRow('Asian L Swept', l['asian_low_swept'] == true ? 'YES' : 'NO',
          l['asian_low_swept'] == true ? _bullish : Colors.white38),
      if (l['sweep_just_happened'] == true)
        Container(
          margin: const EdgeInsets.only(top: 8),
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: _gold.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(children: [
            Icon(Icons.bolt, color: _gold, size: 14),
            const SizedBox(width: 6),
            Text('Sweep just happened! — ${l['sweep_direction'] ?? ''}',
                style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.w600)),
          ]),
        ),
      const SizedBox(height: 8),
      if (l['nearest_bsl'] != null)
        _infoRow('Nearest BSL', '${l['nearest_bsl']}', _bearish),
      if (l['nearest_ssl'] != null)
        _infoRow('Nearest SSL', '${l['nearest_ssl']}', _bullish),
    ]);
  }

  // ------------------------------------------------------------
  // MOMENTUM
  // ------------------------------------------------------------

  Widget _buildMomentumCard() {
    final m = _market?['momentum'];
    if (m == null) return const SizedBox();

    return _buildCard('MOMENTUM', m['score'], [
      _infoRow('RSI M5',  '${m['rsi_m5']  ?? '—'}', Colors.white70),
      _infoRow('RSI M15', '${m['rsi_m15'] ?? '—'}  ${m['rsi_m15_signal'] ?? ''}', Colors.white70),
      _infoRow('RSI H1',  '${m['rsi_h1']  ?? '—'}', Colors.white70),
      _infoRow('Divergence',
          m['divergence'] == true ? (m['divergence_type'] ?? 'YES') : 'None',
          m['divergence'] == true ? _gold : Colors.white38),
      _infoRow('Volume Spike', m['volume_spike'] == true ? 'YES' : 'No',
          m['volume_spike'] == true ? _gold : Colors.white38),
    ]);
  }


  // ------------------------------------------------------------
  // LEVELS & PIVOTS
  // ------------------------------------------------------------

  Widget _buildLevelsCard() {
    final l = _market?['levels'];
    if (l == null) return const SizedBox();

    return _buildCard('LEVELS & PIVOTS', l['score'], [
      _infoRow('At Key Level', l['at_key_level'] == true ? 'YES ✓' : 'No',
          l['at_key_level'] == true ? _gold : Colors.white38),
      if (l['closest_level'] != null)
        _infoRow('Closest',
            '${l['closest_level']['label']} — ${l['closest_level']['level']}',
            _gold),
      _infoRow('VWAP', '${l['vwap'] ?? '—'}', Colors.white54),
      const Padding(padding: EdgeInsets.symmetric(vertical: 4),
          child: Divider(color: Colors.white12, height: 1)),
      Text('DAILY PIVOTS', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 1.2)),
      const SizedBox(height: 6),
      _infoRow('dPP', '${l['pivot_pp'] ?? '—'}', Colors.white70),
      _infoRow('dR1 / dS1', '${l['pivot_r1'] ?? '—'}  /  ${l['pivot_s1'] ?? '—'}',
          Colors.white54),
      _infoRow('dR2 / dS2', '${l['pivot_r2'] ?? '—'}  /  ${l['pivot_s2'] ?? '—'}',
          Colors.white38),
      _infoRow('dR3 / dS3', '${l['pivot_r3'] ?? '—'}  /  ${l['pivot_s3'] ?? '—'}',
          Colors.white24),
      const Padding(padding: EdgeInsets.symmetric(vertical: 4),
          child: Divider(color: Colors.white12, height: 1)),
      Text('WEEKLY PIVOTS', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 1.2)),
      const SizedBox(height: 6),
      _infoRow('wPP', '${l['weekly_pp'] ?? '—'}', Colors.white70),
      _infoRow('wR1 / wS1', '${l['weekly_r1'] ?? '—'}  /  ${l['weekly_s1'] ?? '—'}', Colors.white54),
      _infoRow('wR2 / wS2', '${l['weekly_r2'] ?? '—'}  /  ${l['weekly_s2'] ?? '—'}', Colors.white38),
      _infoRow('wR3 / wS3', '${l['weekly_r3'] ?? '—'}  /  ${l['weekly_s3'] ?? '—'}', Colors.white24),
      const Padding(padding: EdgeInsets.symmetric(vertical: 4),
          child: Divider(color: Colors.white12, height: 1)),
      Text('MONTHLY PIVOTS', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 1.2)),
      const SizedBox(height: 6),
      _infoRow('mPP', '${l['monthly_pp'] ?? '—'}', Colors.white70),
      _infoRow('mR1 / mS1', '${l['monthly_r1'] ?? '—'}  /  ${l['monthly_s1'] ?? '—'}', Colors.white54),
      _infoRow('mR2 / mS2', '${l['monthly_r2'] ?? '—'}  /  ${l['monthly_s2'] ?? '—'}', Colors.white38),
      _infoRow('mR3 / mS3', '${l['monthly_r3'] ?? '—'}  /  ${l['monthly_s3'] ?? '—'}', Colors.white24),

      const Padding(padding: EdgeInsets.symmetric(vertical: 4),
          child: Divider(color: Colors.white12, height: 1)),
      Text('PREMIUM / DISCOUNT', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 1.2)),
      const SizedBox(height: 6),
      _infoRow('Price Zone', (l['price_zone'] ?? '—').toUpperCase(),
          l['price_zone'] == 'premium' ? _bearish : l['price_zone'] == 'discount' ? _bullish : Colors.white54),
      _infoRow('Equilibrium', '${l['equilibrium'] ?? '—'}', Colors.white54),
      _infoRow('In OTE Zone', l['in_ote'] == true ? 'YES ✓' : 'No',
          l['in_ote'] == true ? _gold : Colors.white38),
      if (l['ndog'] != null)
        _infoRow('NDOG CE', '${(l['ndog'] as Map)['ce']}', Colors.white54),
      if (l['nwog'] != null)
        _infoRow('NWOG CE', '${(l['nwog'] as Map)['ce']}', Colors.white54),
    ]);
  }

  Widget _buildFibsCard() {
    final e = _market?['entry'];
    if (e == null) return const SizedBox();

    final fibs = (e['golden_fibs'] as List?) ?? [];
    final allFibs = (e['fibs'] as List?) ?? [];
    if (allFibs.isEmpty) return const SizedBox();

    return _buildCard('FIBONACCI', null, [
      _infoRow('Direction', (e['fib_direction'] ?? '—').toUpperCase(),
          _biasColor(e['fib_direction'])),
      const SizedBox(height: 6),
      if (fibs.isNotEmpty) ...[
        Text('GOLDEN ZONE (Key Levels)',
            style: TextStyle(color: _gold, fontSize: 10, letterSpacing: 1)),
        const SizedBox(height: 6),
        ...fibs.map((f) => Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            Container(width: 8, height: 8,
                decoration: const BoxDecoration(color: Color(0xFFFFD700), shape: BoxShape.circle)),
            const SizedBox(width: 8),
            Text(f['label']?.toString() ?? '', style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.bold)),
            const Spacer(),
            Text('${f['level'] ?? '—'}',
                style: const TextStyle(color: Colors.white70, fontSize: 12,
                    fontFeatures: [FontFeature.tabularFigures()])),
          ]),
        )),
        const Padding(padding: EdgeInsets.symmetric(vertical: 4),
            child: Divider(color: Colors.white12, height: 1)),
      ],
      Text('ALL LEVELS', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 1)),
      const SizedBox(height: 6),
      ...allFibs.map((f) => Padding(
        padding: const EdgeInsets.only(bottom: 3),
        child: _infoRow(
          f['label']?.toString() ?? '',
          '${f['level'] ?? '—'}',
          (f['is_golden'] == true) ? _gold : Colors.white38,
        ),
      )),
    ]);
  }

  // ------------------------------------------------------------
  // ENTRY ZONES
  // ------------------------------------------------------------

  Widget _buildEntryCard() {
    final e = _market?['entry'];
    if (e == null) return const SizedBox();

    return _buildCard('ENTRY ZONES', e['score'], [
      _infoRow('Bull OBs',  '${e['bull_ob_count']}', e['bull_ob_count'] > 0 ? _bullish : Colors.white38),
      _infoRow('Bear OBs',  '${e['bear_ob_count']}', e['bear_ob_count'] > 0 ? _bearish : Colors.white38),
      _infoRow('Bull FVGs', '${e['bull_fvg_count']}', e['bull_fvg_count'] > 0 ? _bullish : Colors.white38),
      _infoRow('Bear FVGs', '${e['bear_fvg_count']}', e['bear_fvg_count'] > 0 ? _bearish : Colors.white38),
      _infoRow('Patterns',  '${e['patterns']}', e['patterns'] > 0 ? _gold : Colors.white38),
      _infoRow('At Zone',   e['at_zone'] == true ? 'YES' : 'No',
          e['at_zone'] == true ? _gold : Colors.white38),
      _infoRow('Entry Bias', (e['entry_bias'] ?? 'neutral').toUpperCase(),
          _biasColor(e['entry_bias'])),
      if (e['in_ote'] == true) ...[
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: _gold.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: _gold.withValues(alpha: 0.4)),
          ),
          child: Row(children: [
            Icon(Icons.my_location_rounded, color: _gold, size: 14),
            const SizedBox(width: 6),
            Text('IN OTE ZONE — Optimal Trade Entry (${(e['ote_direction'] ?? '').toUpperCase()})',
                style: TextStyle(color: _gold, fontSize: 11, fontWeight: FontWeight.w600)),
          ]),
        ),
      ],
    ]);
  }

  // ------------------------------------------------------------
  // MODELS
  // ------------------------------------------------------------

  Widget _buildModelsCard() {
    final m = _market?['models'];
    if (m == null) return const SizedBox();

    final sbWindow = m['silver_bullet_window'] as String?;
    final sbActive = m['silver_bullet_active'] == true;

    final allScores = m['all_scores'] as Map? ?? {};

    return _buildCard('MODELS', m['model_score'], [
      // Silver Bullet — subtle one-liner
      if (sbWindow != null) Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(children: [
          Icon(sbActive ? Icons.bolt_rounded : Icons.access_time_rounded,
              size: 11, color: sbActive ? const Color(0xFFFFD700) : Colors.white24),
          const SizedBox(width: 4),
          Text(sbActive ? 'Silver Bullet active — $sbWindow' : 'SB: $sbWindow',
              style: TextStyle(fontSize: 10,
                  color: sbActive ? const Color(0xFFFFD700) : Colors.white38)),
        ]),
      ),
            _infoRow('Active', m['active_model']?.toString().replaceAll('_', ' ') ?? 'None', _gold),
      _infoRow('Validated', '${m['validated_count']}/10', Colors.white70),
      const SizedBox(height: 8),
      ...allScores.entries.map((e) {
        final score = (e.value ?? 0).toDouble();
        return Padding(
          padding: const EdgeInsets.only(bottom: 5),
          child: Row(children: [
            Expanded(
              child: Text(
                e.key.toString().replaceAll('_', ' '),
                style: TextStyle(color: Colors.white38, fontSize: 11),
              ),
            ),
            SizedBox(
              width: 80,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(3),
                child: LinearProgressIndicator(
                  value: score / 100,
                  backgroundColor: Colors.white.withValues(alpha: 0.08),
                  valueColor: AlwaysStoppedAnimation(
                    score >= 70 ? _bullish : score >= 50 ? _gold : Colors.white24,
                  ),
                  minHeight: 4,
                ),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              width: 28,
              child: Text(
                '${score.toInt()}',
                style: TextStyle(
                  color: score >= 70 ? _bullish : Colors.white38,
                  fontSize: 11,
                  fontWeight: score >= 70 ? FontWeight.bold : FontWeight.normal,
                ),
                textAlign: TextAlign.right,
              ),
            ),
          ]),
        );
      }),
    ]);
  }

  // ------------------------------------------------------------
  // NEWS
  // ------------------------------------------------------------

  Widget _buildNewsCard() {
    final n = _market?['news'];
    if (n == null) return const SizedBox();

    final upcoming = n['upcoming'] as List? ?? [];

    return _buildCard('NEWS FILTER', null, [  // score hidden — status shows CLEAR/BLOCKED instead
      _infoRow('Status', n['blocked'] == true ? 'BLOCKED' : 'CLEAR',
          n['blocked'] == true ? _bearish : _bullish),
      if (n['next_event'] != null)
        _infoRow('Next Event',
            '${n['minutes_to_next']?.toInt() ?? '—'}min — ${(n['next_event'] as Map?)?.get('title') ?? ''}',
            Colors.orange),
      if (upcoming.isNotEmpty) ...[
        const SizedBox(height: 8),
        ...upcoming.map((ev) {
          final impact = ev['impact'] ?? '';
          return Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(children: [
              Icon(
                impact == 'high' ? Icons.circle : Icons.circle_outlined,
                size: 8,
                color: impact == 'high' ? _bearish : Colors.orange,
              ),
              const SizedBox(width: 8),
              Text(
                '${ev['minutes_away']?.toInt()}min',
                style: TextStyle(color: Colors.white38, fontSize: 11, fontFeatures: const [FontFeature.tabularFigures()]),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  ev['title'] ?? '',
                  style: TextStyle(color: Colors.white54, fontSize: 11),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ]),
          );
        }),
      ],
    ]);
  }

  // ------------------------------------------------------------
  // SHARED HELPERS
  // ------------------------------------------------------------

  Widget _buildCard(String title, dynamic score, List<Widget> children) {
    final scoreVal = score != null ? (score as num).toDouble() : null;
    final scoreColor = scoreVal == null ? Colors.white38
        : scoreVal >= 70 ? _bullish
        : scoreVal >= 40 ? _gold
        : Colors.white38;

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
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(title, style: TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1.2)),
              if (scoreVal != null)
                Text(
                  '${scoreVal.toInt()}/100',
                  style: TextStyle(color: scoreColor, fontSize: 12, fontWeight: FontWeight.w600),
                ),
            ],
          ),
          const SizedBox(height: 12),
          ...children,
        ],
      ),
    );
  }

  Widget _infoRow(String label, String value, Color valueColor) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: Colors.white38, fontSize: 12)),
          Text(value, style: TextStyle(color: valueColor, fontSize: 12, fontWeight: FontWeight.w500)),
        ],
      ),
    );
  }
}

extension MapGet on Map {
  dynamic get(String key) => this[key];
}