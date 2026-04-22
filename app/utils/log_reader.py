import os
import re
import threading
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
from typing import List, Dict, Optional, Tuple


class DictWithDotAccess(dict):
    """支持点号访问的字典类"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._convert_nested()

    def _convert_nested(self):
        for key, value in self.items():
            if isinstance(value, dict):
                self[key] = DictWithDotAccess(value)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return None

    def __setattr__(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        value = super().get(key)
        if isinstance(value, dict):
            return DictWithDotAccess(value)
        return value if value is not None else default

    def or_else(self, key, default_value):
        value = self.get(key)
        if value is None or value == '':
            return default_value
        return value


class LocalLogReader:
    """本地日志文件读取器，支持多线程和高效分页"""

    MAX_CACHE_SIZE = 100

    def __init__(self, log_dir="/var/log/remote/"):
        self.log_dir = log_dir
        self.executor = ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 4) * 2))
        self.log_cache = OrderedDict()
        self.cache_timeout = 300

    def _get_db_server_ips(self) -> set:
        """从数据库获取已注册的服务器IP列表（请求内缓存 via Flask g）"""
        from flask import g
        cache_key = '_log_db_server_ips'
        if hasattr(g, cache_key):
            return getattr(g, cache_key)
        try:
            from app.models.server import Server
            servers = Server.query.all()
            result = set(s.ip for s in servers)
            setattr(g, cache_key, result)
            return result
        except Exception as e:
            print(f"从数据库获取服务器列表失败: {e}")
            return set()

    def get_available_dates(self) -> List[str]:
        """获取可用的日期列表"""
        try:
            dates = []
            for item in os.listdir(self.log_dir):
                item_path = os.path.join(self.log_dir, item)
                if os.path.isdir(item_path) and re.match(r'\d{4}-\d{2}-\d{2}', item):
                    dates.append(item)
            return sorted(dates, reverse=True)
        except Exception as e:
            print(f"获取日期列表失败: {e}")
            return []

    def get_available_servers(self, date: str) -> List[str]:
        """获取指定日期的服务器列表（仅返回数据库中已注册的服务器）"""
        try:
            date_dir = os.path.join(self.log_dir, date)
            if not os.path.exists(date_dir):
                return []

            db_servers = self._get_db_server_ips()
            servers = []
            for item in os.listdir(date_dir):
                if item.endswith('.log'):
                    server_ip = item[:-4]
                    if server_ip in db_servers:
                        servers.append(server_ip)
            return sorted(servers)
        except Exception as e:
            print(f"获取服务器列表失败: {e}")
            return []

    ANSI_ESCAPE_RE = re.compile(r'#033\[[0-9;]*m|\x1b\[[0-9;]*m')

    def parse_log_line(self, line: str, date: str = None) -> Optional[Dict]:
        """解析日志行"""
        try:
            # Strip ANSI escape codes (both #033[...m literal and \x1b[...m actual ESC)
            cleaned = self.ANSI_ESCAPE_RE.sub('', line.strip())

            pattern = r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+([a-zA-Z0-9.-]+)\s+([^:]+):\s*(.*)$'
            match = re.match(pattern, cleaned)

            if match:
                timestamp_str, hostname, process, message = match.groups()

                current_year = int(date[:4]) if date and len(date) >= 4 and date[:2] in ('20', '19') else datetime.now().year
                timestamp = datetime.strptime(f"{current_year} {timestamp_str}", "%Y %b %d %H:%M:%S")

                message_lower = message.lower()
                level = 'info'
                # Word-boundary matching avoids false positives like "no error" → error
                if re.search(r'\b(critical|fatal|panic|emerg)\b', message_lower):
                    level = 'critical'
                elif re.search(r'\b(error|err|failed|failure)\b', message_lower):
                    level = 'error'
                elif re.search(r'\b(warn|warning)\b', message_lower):
                    level = 'warning'
                elif re.search(r'\b(debug)\b', message_lower):
                    level = 'debug'

                return {
                    'timestamp': timestamp,
                    'hostname': hostname,
                    'process': process,
                    'message': message,
                    'level': level,
                    'raw': cleaned
                }
        except Exception as e:
            fallback = line.strip()
            return {
                'timestamp': datetime.min,
                'hostname': 'unknown',
                'process': 'unknown',
                'message': fallback,
                'level': 'unknown',
                'raw': fallback
            }
        return None

    def search_logs(self, date, server_ips=None, level=None, keyword=None, page=1, per_page=50):
        """搜索日志（保留向后兼容）"""
        result = self.search_logs_with_stats(date, server_ips, level, keyword, page, per_page)
        return {
            'logs': result['logs'],
            'total': result['total'],
            'page': result['page'],
            'per_page': result['per_page'],
            'total_pages': result['total_pages']
        }

    def search_logs_with_stats(self, date, server_ips=None, level=None, keyword=None, page=1, per_page=50):
        """搜索日志并同时计算统计信息，避免重复读取文件"""
        sorted_ips = sorted(server_ips or [])
        cache_key = f"{date}_{sorted_ips}_{level}_{keyword}_{page}_{per_page}"
        current_time = time.time()

        # Check cache and purge stale entries
        if cache_key in self.log_cache:
            cached_data, cache_time = self.log_cache[cache_key]
            if current_time - cache_time < self.cache_timeout:
                self.log_cache.move_to_end(cache_key)
                return cached_data
            else:
                del self.log_cache[cache_key]

        try:
            date_dir = os.path.join(self.log_dir, date)
            if not os.path.exists(date_dir):
                empty_result = {
                    'logs': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 1,
                    'stats': DictWithDotAccess({'total_lines': 0, 'by_level': {}, 'by_server': {}, 'file_count': 0})
                }
                self.log_cache[cache_key] = (empty_result, current_time)
                self.log_cache.move_to_end(cache_key)
                self._evict_cache()
                return empty_result

            db_servers = self._get_db_server_ips()

            if server_ips:
                target_files = [os.path.join(date_dir, f"{ip}.log") for ip in server_ips if ip in db_servers]
            else:
                target_files = [os.path.join(date_dir, f) for f in os.listdir(date_dir) if f.endswith('.log') and f[:-4] in db_servers]

            target_files = [f for f in target_files if os.path.exists(f)]

            if not target_files:
                empty_result = {
                    'logs': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 1,
                    'stats': DictWithDotAccess({'total_lines': 0, 'by_level': {}, 'by_server': {}, 'file_count': 0})
                }
                self.log_cache[cache_key] = (empty_result, current_time)
                self.log_cache.move_to_end(cache_key)
                self._evict_cache()
                return empty_result

            # Single-pass: search + stats together
            all_logs = []
            stats_data = {
                'total_lines': 0,
                'by_level': defaultdict(int),
                'by_server': defaultdict(int),
                'file_count': len(target_files)
            }

            future_to_file = {}
            for file_path in target_files:
                future = self.executor.submit(self._search_single_file_with_stats, file_path, level, keyword, date)
                future_to_file[future] = file_path

            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    logs, level_counts, total_lines = future.result(timeout=120)
                    all_logs.extend(logs)
                    server_ip = os.path.basename(file_path)[:-4]
                    stats_data['total_lines'] += total_lines
                    stats_data['by_server'][server_ip] = total_lines
                    for lvl, count in level_counts.items():
                        stats_data['by_level'][lvl] += count
                except Exception as e:
                    print(f"搜索文件超时或失败 {file_path}: {e}")

            all_logs.sort(key=lambda x: x['timestamp'], reverse=True)

            total = len(all_logs)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_logs = all_logs[start_idx:end_idx]

            result = {
                'logs': paginated_logs,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page if total > 0 else 1,
                'stats': DictWithDotAccess({
                    'total_lines': stats_data['total_lines'],
                    'by_level': dict(stats_data['by_level']),
                    'by_server': dict(stats_data['by_server']),
                    'file_count': stats_data['file_count']
                })
            }

            self.log_cache[cache_key] = (result, current_time)
            self.log_cache.move_to_end(cache_key)
            self._evict_cache()

            return result

        except Exception as e:
            print(f"搜索日志失败: {e}")
            error_result = {
                'logs': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 1,
                'stats': DictWithDotAccess({'total_lines': 0, 'by_level': {}, 'by_server': {}, 'file_count': 0})
            }
            return error_result

    def _search_single_file_with_stats(self, file_path: str, level: str = None, keyword: str = None, date: str = None) -> Tuple[List[Dict], Dict, int]:
        """搜索单个文件并同时收集统计信息"""
        logs = []
        level_counts = defaultdict(int)
        total_lines = 0

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f):
                    total_lines += 1
                    parsed_log = self.parse_log_line(line, date=date)
                    if not parsed_log:
                        continue

                    level_counts[parsed_log['level']] += 1

                    if level and parsed_log['level'] != level:
                        continue

                    if keyword and keyword.lower() not in parsed_log['message'].lower():
                        continue

                    parsed_log['file_path'] = file_path
                    parsed_log['line_number'] = line_num + 1
                    logs.append(parsed_log)

        except Exception as e:
            print(f"搜索单个文件失败 {file_path}: {e}")

        return logs, dict(level_counts), total_lines

    def get_log_stats(self, date: str, server_ips: List[str] = None) -> DictWithDotAccess:
        """获取日志统计信息（保留向后兼容，内部调用 search_logs_with_stats 的缓存结果）"""
        sorted_ips = sorted(server_ips or [])
        cache_key = f"{date}_{sorted_ips}_{None}_{None}_{1}_{1}"
        current_time = time.time()

        # Try to reuse cached combined result
        if cache_key in self.log_cache:
            cached_data, cache_time = self.log_cache[cache_key]
            if current_time - cache_time < self.cache_timeout:
                return cached_data.get('stats', DictWithDotAccess({'total_lines': 0, 'by_level': {}, 'by_server': {}, 'file_count': 0}))

        # Fallback: compute stats directly
        result = self.search_logs_with_stats(date, server_ips, level=None, keyword=None, page=1, per_page=1)
        return result['stats']

    def _evict_cache(self):
        """Evict oldest cache entries when over max size"""
        while len(self.log_cache) > self.MAX_CACHE_SIZE:
            self.log_cache.popitem(last=False)

    def clear_cache(self):
        """清理缓存"""
        self.log_cache.clear()

    def __del__(self):
        """清理资源"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)