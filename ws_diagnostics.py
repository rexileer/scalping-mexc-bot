#!/usr/bin/env python3
"""
Простой скрипт диагностики WebSocket без aiohttp зависимостей.
Анализирует логи и состояние системы.
"""

import os
import sys
import re
from datetime import datetime, timedelta

def analyze_logs():
    """Анализируем логи на предмет WebSocket проблем."""
    print("=== WebSocket Log Analysis ===")
    
    log_file = "bot_logs.log"
    if not os.path.exists(log_file):
        print("❌ Log file not found")
        return
    
    # Паттерны для поиска
    patterns = {
        'connections': r'Connected (\w+) (\d+) to WebSocket',
        'disconnections': r'WebSocket for (\w+) (\d+) closed',
        'market_connect': r'Connected to market data WebSocket',
        'market_disconnect': r'Disconnected from market data WebSocket',
        'session_leaks': r'Обнаружено (\d+) клиентских сессий',
        'subscription_success': r'Subscribed to (\w+) data for: \[(.*?)\]',
        'mexc_timeouts': r'30 seconds|30 сек',
        'concurrent_errors': r'Concurrent call to receive\(\)',
        'ping_errors': r'Error sending ping'
    }
    
    stats = {key: [] for key in patterns.keys()}
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            # Читаем только последние 1000 строк для производительности
            lines = f.readlines()[-1000:]
            
        for line in lines:
            for pattern_name, pattern in patterns.items():
                matches = re.findall(pattern, line)
                if matches:
                    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    timestamp = timestamp_match.group(1) if timestamp_match else "unknown"
                    stats[pattern_name].append({
                        'timestamp': timestamp,
                        'data': matches,
                        'line': line.strip()
                    })
    
    except Exception as e:
        print(f"❌ Error reading log file: {e}")
        return
    
    # Анализируем результаты
    print(f"\n📊 Analysis Results (last 1000 log lines):")
    print(f"🔗 User connections: {len(stats['connections'])}")
    print(f"🔌 User disconnections: {len(stats['disconnections'])}")
    print(f"📈 Market connections: {len(stats['market_connect'])}")
    print(f"📉 Market disconnections: {len(stats['market_disconnect'])}")
    print(f"🏓 Ping errors: {len(stats['ping_errors'])}")
    print(f"⚡ Concurrent receive errors: {len(stats['concurrent_errors'])}")
    
    # Анализ session leaks
    if stats['session_leaks']:
        latest_leak = stats['session_leaks'][-1]
        session_count = latest_leak['data'][0] if latest_leak['data'] else 'unknown'
        print(f"💧 Session leaks detected: {session_count} sessions")
        if int(session_count) > 10:
            print("⚠️  HIGH SESSION COUNT - cleanup needed!")
    
    # Анализ подписок
    if stats['subscription_success']:
        print(f"✅ Successful subscriptions: {len(stats['subscription_success'])}")
        
    # Последние ошибки
    print(f"\n🔴 Recent Issues:")
    for error_type in ['ping_errors', 'concurrent_errors']:
        if stats[error_type]:
            recent = stats[error_type][-3:]  # Последние 3 ошибки
            for error in recent:
                print(f"   {error_type}: {error['timestamp']}")
    
    # Рекомендации
    print(f"\n💡 Recommendations:")
    
    if len(stats['concurrent_errors']) > 0:
        print("   - Fix concurrent receive() errors - multiple listeners detected")
        
    if len(stats['disconnections']) > len(stats['connections']) * 1.5:
        print("   - Too many disconnections vs connections - connection instability")
        
    if stats['session_leaks']:
        latest_count = int(stats['session_leaks'][-1]['data'][0])
        expected_count = 8  # 7 users + 1 market
        if latest_count > expected_count * 2:
            print(f"   - Session leak detected: {latest_count} vs expected ~{expected_count}")
            print("   - Run emergency cleanup immediately")
    
    if len(stats['market_disconnect']) > 3:
        print("   - Market connection unstable - check MEXC subscription validity")

def check_docker_status():
    """Проверяем статус Docker контейнера."""
    print("\n=== Docker Status ===")
    
    try:
        import subprocess
        result = subprocess.run(['docker', 'ps', '--filter', 'name=scalpingbot'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                print("✅ ScalpingBot container is running")
                # Парсим статус
                status_line = lines[1]
                if 'Up' in status_line:
                    uptime_match = re.search(r'Up ([^,]+)', status_line)
                    if uptime_match:
                        print(f"⏱️  Uptime: {uptime_match.group(1)}")
            else:
                print("❌ ScalpingBot container not found")
        else:
            print("❌ Error checking Docker status")
    except Exception as e:
        print(f"❌ Error checking Docker: {e}")

def suggest_fixes():
    """Предлагаем исправления."""
    print("\n=== Suggested Fixes ===")
    
    print("1. 🔧 Restart WebSocket connections:")
    print("   docker restart scalpingbot")
    
    print("\n2. 🧹 Emergency cleanup (if high session count):")
    print("   # Add this to your Telegram bot commands:")
    print("   # await websocket_manager.emergency_session_cleanup()")
    
    print("\n3. 📊 Monitor in real-time:")
    print("   docker logs -f scalpingbot | grep -E 'WebSocket|session|connect'")
    
    print("\n4. 🔍 Check current connections:")
    print("   # Use Telegram bot stats command to check:")
    print("   # - User connections count")
    print("   # - Market connection status")
    print("   # - Active sessions count")

def main():
    """Основная функция."""
    print("🔍 WebSocket Diagnostics Tool")
    print("=" * 50)
    
    analyze_logs()
    check_docker_status()
    suggest_fixes()
    
    print("\n" + "=" * 50)
    print("✅ Diagnostics complete")

if __name__ == "__main__":
    main()