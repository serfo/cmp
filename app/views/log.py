from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required, current_user
from app import db
from app.models.server import Server
from app.models.ai_analysis import AIAnalysis
from app.utils.ai_utils import AIAnalyzer
from app.utils.log_reader import LocalLogReader, DictWithDotAccess
from app.config import Config
import csv
from io import StringIO
from datetime import datetime
import json

# 初始化AI分析器和日志读取器
aio_analyzer = AIAnalyzer()
log_reader = LocalLogReader()

# 创建蓝图
log_bp = Blueprint('log', __name__)

@log_bp.route('/')
@login_required
def index():
    """日志查询 - 从本地文件读取"""
    # 获取查询参数
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    level = request.args.get('level')
    keyword = request.args.get('keyword')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Handle server_ips: both comma-separated string and multi-param
    raw_server_ips = request.args.getlist('server_ips')
    if raw_server_ips and len(raw_server_ips) == 1 and ',' in raw_server_ips[0]:
        server_ips = [ip.strip() for ip in raw_server_ips[0].split(',') if ip.strip()]
    else:
        server_ips = [ip.strip() for ip in raw_server_ips if ip.strip()]

    # 限制每页显示数量，最多100条
    per_page = min(per_page, 100)

    # 获取可用的日期列表
    available_dates = log_reader.get_available_dates()

    # 获取指定日期的服务器列表
    available_servers = log_reader.get_available_servers(date) if date in available_dates else []

    # 如果没有选择服务器，默认选择所有服务器
    if not server_ips and available_servers:
        server_ips = available_servers

    # Combined search + stats in one pass
    result = log_reader.search_logs_with_stats(
        date=date,
        server_ips=server_ips,
        level=level or '',
        keyword=keyword or '',
        page=page,
        per_page=per_page
    )

    logs = result['logs']
    total = result['total']
    total_pages = result['total_pages']
    stats = result['stats']

    # 创建分页对象（兼容模板）
    class Pagination:
        def __init__(self, page, per_page, total):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = total_pages
            self.has_prev = page > 1
            self.has_next = page < total_pages
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None

        def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
            last = self.pages
            for num in range(1, last + 1):
                if num <= left_edge or \
                   (num > self.page - left_current - 1 and num < self.page + right_current) or \
                   num > last - right_edge:
                    yield num

    pagination = Pagination(page, per_page, total)

    # 添加日志级别选项
    log_levels = ['debug', 'info', 'warning', 'error', 'critical', 'unknown']

    # 检查是否有结果
    if not logs and (server_ips or level or keyword):
        stats_dict = dict(stats) if isinstance(stats, DictWithDotAccess) else stats
        stats_dict['no_results'] = True
        stats_dict['suggestions'] = [
            '尝试放宽过滤条件',
            '检查日期是否正确',
            '检查服务器是否有日志文件'
        ]
        stats = DictWithDotAccess(stats_dict)
    elif not available_dates:
        stats_dict = dict(stats) if isinstance(stats, DictWithDotAccess) else stats
        stats_dict['no_results'] = True
        stats_dict['suggestions'] = ['/var/log/remote/ 目录中没有日志文件']
        stats = DictWithDotAccess(stats_dict)

    # 今天的日期字符串，用于模板中标注"(今天)"
    today_str = datetime.now().strftime('%Y-%m-%d')

    return render_template('log/index.html',
                         logs=logs,
                         total=total,
                         available_servers=available_servers,
                         available_dates=available_dates,
                         selected_date=date,
                         selected_servers=server_ips,
                         log_types=log_levels,
                         level=level,
                         keyword=keyword,
                         per_page=per_page,
                         pagination=pagination,
                         stats=stats,
                         today_str=today_str)

@log_bp.route('/api/servers/<date>')
@login_required
def api_servers_by_date(date):
    """API: 获取指定日期的服务器列表"""
    try:
        servers = log_reader.get_available_servers(date)
        return jsonify({
            'success': True,
            'data': servers,
            'count': len(servers)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取服务器列表失败: {str(e)}'
        }), 500

@log_bp.route('/api/search')
@login_required
def api_search():
    """API: 异步搜索日志"""
    try:
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        server_ips_str = request.args.get('server_ips', '')
        level = request.args.get('level', '')
        keyword = request.args.get('keyword', '')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)

        per_page = min(per_page, 100)

        server_list = [ip.strip() for ip in server_ips_str.split(',') if ip.strip()] if server_ips_str else []

        # Combined search + stats
        result = log_reader.search_logs_with_stats(
            date=date,
            server_ips=server_list,
            level=level,
            keyword=keyword,
            page=page,
            per_page=per_page
        )

        logs = result['logs']
        total = result['total']
        total_pages = result['total_pages']
        stats = result['stats']

        pagination = {
            'page': page,
            'per_page': per_page,
            'pages': total_pages,
            'total': total,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'prev_num': page - 1 if page > 1 else None,
            'next_num': page + 1 if page < total_pages else None,
            'pages_list': list(range(1, min(total_pages + 1, 8))) if total_pages <= 7 else _generate_pages_list(page, total_pages)
        }

        return jsonify({
            'success': True,
            'logs': logs,
            'pagination': pagination,
            'stats': dict(stats) if isinstance(stats, DictWithDotAccess) else stats,
            'total': total
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'搜索失败: {str(e)}'
        }), 500

def _generate_pages_list(current, total):
    """生成分页页码列表"""
    pages = []
    if total <= 7:
        return list(range(1, total + 1))

    pages.append(1)
    if current > 3:
        pages.append('...')

    start = max(2, current - 1)
    end = min(total - 1, current + 1)

    for p in range(start, end + 1):
        if p not in pages:
            pages.append(p)

    if current < total - 2:
        pages.append('...')
    pages.append(total)

    return pages

@log_bp.route('/analysis', methods=['GET', 'POST'])
@login_required
def analysis():
    """日志分析"""
    log_content = request.args.get('log_content', '')
    analysis_type = request.form.get('analysis_type', 'error_detection')
    result = None
    ai_quota = {
        'total': current_user.ai_quota,
        'used': current_user.ai_used,
        'remaining': current_user.ai_quota - current_user.ai_used
    }

    if request.method == 'POST':
        log_content = request.form.get('log_content', '')

        # 检查AI配额
        if current_user.ai_used >= current_user.ai_quota:
            return render_template('log/analysis.html',
                                 log_content=log_content,
                                 analysis_type=analysis_type,
                                 result=result,
                                 ai_quota=ai_quota,
                                 error="AI分析配额不足，请联系管理员")

        # 使用DeepSeek AI进行日志分析
        result = aio_analyzer.analyze_log(log_content, analysis_type)
        result['analysis_type'] = analysis_type

        # 保存分析记录到数据库
        ai_analysis = AIAnalysis(
            user_id=current_user.id,
            log_content=log_content,
            analysis_type=analysis_type,
            conclusion=result['conclusion'],
            suggestions=json.dumps(result['suggestions']),
            confidence=result['confidence'],
            raw_response=result.get('raw_response')
        )
        db.session.add(ai_analysis)

        # 更新用户AI使用计数
        current_user.ai_used += 1
        db.session.commit()

        # 更新配额信息
        ai_quota['used'] = current_user.ai_used
        ai_quota['remaining'] = current_user.ai_quota - current_user.ai_used

    return render_template('log/analysis.html',
                         log_content=log_content,
                         analysis_type=analysis_type,
                         result=result,
                         ai_quota=ai_quota,
                         error=None)