// ============================================================
// signal_model.dart — Data Models
// ============================================================

class SignalModel {
  final bool shouldTrade;
  final bool blocked;
  final String? blockedReason;
  final String direction;
  final String grade;
  final double score;
  final bool scoreFrozen;
  final String signalSummary;

  final double? entry;
  final double? sl;
  final double? tp1;
  final double? tp2;
  final double? tp3;
  final double? slPips;
  final double? lotSize;
  final String? entryZone;

  final String? modelName;
  final double? modelScore;
  final int validatedCount;

  final String tradeStatus;
  final String stateMessage;

  final String session;
  final double? atr;
  final double? spreadPips;
  final String volatility;

  final bool newsBlocked;
  final String? nextNews;
  final double? minutesToNews;

  final String cotSentiment;
  final double? cotLongPct;

  final double healthScore;
  final double winrate30d;
  final int totalTrades30d;

  final DateTime time;

  SignalModel({
    required this.shouldTrade,
    required this.blocked,
    this.blockedReason,
    required this.direction,
    required this.grade,
    required this.score,
    required this.scoreFrozen,
    required this.signalSummary,
    this.entry,
    this.sl,
    this.tp1,
    this.tp2,
    this.tp3,
    this.slPips,
    this.lotSize,
    this.entryZone,
    this.modelName,
    this.modelScore,
    required this.validatedCount,
    required this.tradeStatus,
    required this.stateMessage,
    required this.session,
    this.atr,
    this.spreadPips,
    required this.volatility,
    required this.newsBlocked,
    this.nextNews,
    this.minutesToNews,
    required this.cotSentiment,
    this.cotLongPct,
    required this.healthScore,
    required this.winrate30d,
    required this.totalTrades30d,
    required this.time,
  });

  factory SignalModel.fromJson(Map<String, dynamic> j) {
    return SignalModel(
      shouldTrade:    j['should_trade']    ?? false,
      blocked:        j['blocked']         ?? false,
      blockedReason:  j['blocked_reason'],
      direction:      j['direction']       ?? 'none',
      grade:          j['grade']           ?? 'NO_TRADE',
      score:          (j['score']          ?? 0).toDouble(),
      scoreFrozen:    j['score_frozen']    ?? false,
      signalSummary:  j['signal_summary']  ?? '',
      entry:          j['entry']?.toDouble(),
      sl:             j['sl']?.toDouble(),
      tp1:            j['tp1']?.toDouble(),
      tp2:            j['tp2']?.toDouble(),
      tp3:            j['tp3']?.toDouble(),
      slPips:         j['sl_pips']?.toDouble(),
      lotSize:        j['lot_size']?.toDouble(),
      entryZone:      j['entry_zone'],
      modelName:      j['model_name'],
      modelScore:     j['model_score']?.toDouble(),
      validatedCount: j['validated_count'] ?? 0,
      tradeStatus:    j['trade_status']    ?? 'IDLE',
      stateMessage:   j['state_message']   ?? '',
      session:        j['session']         ?? 'unknown',
      atr:            j['atr']?.toDouble(),
      spreadPips:     j['spread_pips']?.toDouble(),
      volatility:     j['volatility']      ?? 'unknown',
      newsBlocked:    j['news_blocked']    ?? false,
      nextNews:       j['next_news'],
      minutesToNews:  j['minutes_to_news']?.toDouble(),
      cotSentiment:   j['cot_sentiment']   ?? 'neutral',
      cotLongPct:     j['cot_long_pct']?.toDouble(),
      healthScore:    (j['health_score']   ?? 100).toDouble(),
      winrate30d:     (j['winrate_30d']    ?? 0).toDouble(),
      totalTrades30d: j['total_trades_30d'] ?? 0,
      time:           DateTime.tryParse(j['time'] ?? '') ?? DateTime.now(),
    );
  }

  bool get isBuy      => direction == 'buy';
  bool get isSell     => direction == 'sell';
  bool get isStrong   => grade == 'STRONG';
  bool get isModerate => grade == 'MODERATE';
  bool get isActive   => tradeStatus == 'ACTIVE';
  bool get isSignal   => tradeStatus == 'SIGNAL';
}


class PriceModel {
  final String symbol;
  final double bid;
  final double ask;
  final double mid;
  final double spread;
  final DateTime time;

  PriceModel({
    required this.symbol,
    required this.bid,
    required this.ask,
    required this.mid,
    required this.spread,
    required this.time,
  });

  factory PriceModel.fromJson(Map<String, dynamic> j) {
    return PriceModel(
      symbol: j['symbol'] ?? 'XAUUSD',
      bid:    (j['bid']    ?? 0).toDouble(),
      ask:    (j['ask']    ?? 0).toDouble(),
      mid:    (j['mid']    ?? 0).toDouble(),
      spread: (j['spread'] ?? 0).toDouble(),
      time:   DateTime.tryParse(j['time'] ?? '') ?? DateTime.now(),
    );
  }
}