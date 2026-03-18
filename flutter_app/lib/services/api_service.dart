// ============================================================
// api_service.dart — API Service
// All HTTP calls to the Python FastAPI backend
// ============================================================

import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  static const String baseUrl = 'http://localhost:8000';
  static const Duration timeout = Duration(seconds: 30);

  // ------------------------------------------------------------
  // SIGNAL — main endpoint
  // ------------------------------------------------------------

  static Future<Map<String, dynamic>> getSignal() async {
    final response = await http
        .get(Uri.parse('$baseUrl/signal'))
        .timeout(timeout);
    if (response.statusCode == 200) {
      return json.decode(response.body);
    }
    throw Exception('Signal fetch failed: ${response.statusCode}');
  }

  // ------------------------------------------------------------
  // MARKET — full engine breakdown
  // ------------------------------------------------------------

  static Future<Map<String, dynamic>> getMarket() async {
    final response = await http
        .get(Uri.parse('$baseUrl/market'))
        .timeout(timeout);
    if (response.statusCode == 200) {
      return json.decode(response.body);
    }
    throw Exception('Market fetch failed: ${response.statusCode}');
  }

  // ------------------------------------------------------------
  // PRICE — live bid/ask
  // ------------------------------------------------------------

  static Future<Map<String, dynamic>> getPrice() async {
    final response = await http
        .get(Uri.parse('$baseUrl/price'))
        .timeout(timeout);
    if (response.statusCode == 200) {
      return json.decode(response.body);
    }
    throw Exception('Price fetch failed: ${response.statusCode}');
  }

  // ------------------------------------------------------------
  // HEALTH — system status
  // ------------------------------------------------------------

  static Future<Map<String, dynamic>> getHealth() async {
    final response = await http
        .get(Uri.parse('$baseUrl/health'))
        .timeout(timeout);
    if (response.statusCode == 200) {
      return json.decode(response.body);
    }
    throw Exception('Health fetch failed: ${response.statusCode}');
  }

  // ------------------------------------------------------------
  // ANALYTICS — performance stats
  // ------------------------------------------------------------

  static Future<Map<String, dynamic>> getAnalytics() async {
    final response = await http
        .get(Uri.parse('$baseUrl/analytics'))
        .timeout(timeout);
    if (response.statusCode == 200) {
      return json.decode(response.body);
    }
    throw Exception('Analytics fetch failed: ${response.statusCode}');
  }

  // ------------------------------------------------------------
  // TRADE STATE
  // ------------------------------------------------------------

  static Future<Map<String, dynamic>> getTradeState() async {
    final response = await http
        .get(Uri.parse('$baseUrl/trade/state'))
        .timeout(timeout);
    if (response.statusCode == 200) {
      return json.decode(response.body);
    }
    throw Exception('Trade state fetch failed: ${response.statusCode}');
  }

  // ------------------------------------------------------------
  // FORCE REFRESH
  // ------------------------------------------------------------

  static Future<bool> forceRefresh() async {
    final response = await http
        .post(Uri.parse('$baseUrl/refresh'))
        .timeout(timeout);
    return response.statusCode == 200;
  }
}