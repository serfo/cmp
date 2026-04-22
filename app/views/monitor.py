from flask import Blueprint, render_template, flash, redirect, url_for, current_app, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models.server import Server
from app.models.alarm_record import AlarmRecord
from app.models.ai_analysis import AIAnalysis
from app.config import Config
from app.utils.zabbix_api import ZabbixAPI
from app.utils.email_utils import send_email
import json
import time
import threading
from datetime import datetime

# 创建蓝图
monitor_bp = Blueprint('monitor', __name__)

# Zabbix severity → app severity string
SEVERITY_MAP = {
    '0': 'info', '1': 'info', '2': 'warning', '3': 'error', '4': 'critical', '5': 'critical'
}

# Zabbix severity → AlarmRecord alarm_level integer
ZABBIX_SEVERITY_TO_ALARM_LEVEL = {
    '0': 0, '1': 0, '2': 1, '3': 2, '4': 3, '5': 3
}

# app severity string → AlarmRecord alarm_level integer (reverse map)
ALARM_LEVEL_MAP = {0: 'info', 1: 'warning', 2: 'error', 3: 'critical'}


class ZabbixAlert:
    """动态告警对象，供模板渲染使用"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def alarm_record_to_zabbix_alert(record):
    """将AlarmRecord转换为模板兼容的ZabbixAlert对象"""
    return ZabbixAlert(
        id=record.alarm_id,
        server=None,
        server_id=None,
        alert_type='zabbix',
        severity=ALARM_LEVEL_MAP.get(record.alarm_level, 'info'),
        message=record.alarm_title,
        created_at=record.trigger_time,
        processed_at=None,
        source='Zabbix'
    )


def auto_analyze_and_notify(new_alarms):
    """对新告警自动执行AI分析并发送邮件通知"""
    if not new_alarms:
        return

    for alarm in new_alarms:
        # 只对 warning/error/critical 级别自动分析
        if alarm.alarm_level < 1:
            continue

        try:
            from app.utils.ai_utils import AIAnalyzer
            from app.models.user import User

            # 使用管理员账户记录分析
            admin = User.query.filter_by(role='admin').first()
            if not admin:
                admin = User.query.first()
            if not admin:
                continue

            # 配额检查
            if admin.ai_used >= admin.ai_quota:
                print(f"[告警轮询] 管理员AI配额不足，跳过自动分析 alarm_id={alarm.alarm_id}")
                continue

            # 构建分析内容
            severity_name = ALARM_LEVEL_MAP.get(alarm.alarm_level, 'info')
            alarm_info = f"告警标题: {alarm.alarm_title}\n告警级别: {severity_name}\n告警时间: {alarm.trigger_time.strftime('%Y-%m-%d %H:%M:%S')}\n资源ID: {alarm.resource_id}"

            ai_analyzer = AIAnalyzer()
            result = ai_analyzer.analyze_log(alarm_info, analysis_type='suggestion')

            # 持久化到 AIAnalysis
            ai_record = AIAnalysis(
                user_id=admin.id,
                log_content=alarm_info,
                analysis_type='alarm_auto',
                conclusion=result['conclusion'],
                suggestions=json.dumps(result['suggestions']),
                confidence=result['confidence'],
                raw_response=result.get('raw_response')
            )
            db.session.add(ai_record)

            admin.ai_used += 1
            db.session.commit()

            # 发送邮件
            try:
                suggestions_text = '\n'.join(
                    [f"{i+1}. {s}" for i, s in enumerate(result['suggestions'])]
                ) if result['suggestions'] else '请查看详细分析'

                subject = f"[告警自动分析] {severity_name.upper()} - {alarm.alarm_title}"
                body = f"""告警自动分析报告：

告警标题：{alarm.alarm_title}
告警级别：{severity_name}
告警时间：{alarm.trigger_time.strftime('%Y-%m-%d %H:%M:%S')}
资源ID：{alarm.resource_id}

=== AI结论 ===
{result['conclusion']}

=== 处理建议 ===
{suggestions_text}
"""
                send_email(subject, ['admin@supome.cn'], body)
            except Exception as email_err:
                print(f"[告警轮询] 发送告警自动分析邮件失败: {str(email_err)}")

        except Exception as e:
            print(f"[告警轮询] 自动分析告警 alarm_id={alarm.alarm_id} 失败: {str(e)}")


def persist_zabbix_alerts(problems):
    """将Zabbix告警持久化到alarm_record表（仅持久化，不触发AI分析）"""
    for problem in problems:
        eventid_str = problem.get('eventid')
        if not eventid_str:
            continue
        try:
            alarm_id = int(eventid_str)
        except (ValueError, TypeError):
            continue

        alarm_level = ZABBIX_SEVERITY_TO_ALARM_LEVEL.get(str(problem.get('severity', '0')), 0)
        clock = problem.get('clock', 0)
        trigger_time = datetime.fromtimestamp(int(clock)) if clock else datetime.now()
        objectid = problem.get('objectid', '')
        r_eventid = problem.get('r_eventid')

        existing = AlarmRecord.query.get(alarm_id)
        if existing:
            if r_eventid:
                existing.status = 1
        else:
            alarm_record = AlarmRecord(
                alarm_id=alarm_id,
                alarm_title=problem.get('name', '未知告警'),
                alarm_content=problem.get('name', '未知告警'),
                alarm_level=alarm_level,
                resource_id=str(objectid) if objectid else '',
                trigger_time=trigger_time,
                status=0
            )
            db.session.add(alarm_record)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"持久化Zabbix告警失败: {str(e)}")


def poll_zabbix_alerts(app):
    """定时轮询Zabbix告警：持久化 + 发现新告警自动AI分析并发邮件"""
    with app.app_context():
        try:
            zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
            problems = zabbix_api.get_active_problems(recent=False)

            new_alarms = []
            for problem in problems:
                eventid_str = problem.get('eventid')
                if not eventid_str:
                    continue
                try:
                    alarm_id = int(eventid_str)
                except (ValueError, TypeError):
                    continue

                alarm_level = ZABBIX_SEVERITY_TO_ALARM_LEVEL.get(str(problem.get('severity', '0')), 0)
                clock = problem.get('clock', 0)
                trigger_time = datetime.fromtimestamp(int(clock)) if clock else datetime.now()
                objectid = problem.get('objectid', '')
                r_eventid = problem.get('r_eventid')

                existing = AlarmRecord.query.get(alarm_id)
                if existing:
                    if r_eventid:
                        existing.status = 1
                else:
                    alarm_record = AlarmRecord(
                        alarm_id=alarm_id,
                        alarm_title=problem.get('name', '未知告警'),
                        alarm_content=problem.get('name', '未知告警'),
                        alarm_level=alarm_level,
                        resource_id=str(objectid) if objectid else '',
                        trigger_time=trigger_time,
                        status=0
                    )
                    db.session.add(alarm_record)
                    new_alarms.append(alarm_record)

            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[告警轮询] 持久化失败: {str(e)}")
                return

            # 更新已恢复的告警状态后也 commit
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

            if new_alarms:
                print(f"[告警轮询] 发现 {len(new_alarms)} 条新告警，触发自动AI分析")
                try:
                    auto_analyze_and_notify(new_alarms)
                except Exception as e:
                    print(f"[告警轮询] 自动分析失败: {str(e)}")
            else:
                print("[告警轮询] 无新告警")

        except Exception as e:
            print(f"[告警轮询] Zabbix API调用失败: {str(e)}")


# 缓存配置
MONITORING_CACHE = {}
CACHE_DURATION = 15
CACHE_LOCK = threading.Lock()

def get_cached_monitoring_data(server_id, zabbix_hostid, force_refresh=False):
    """获取缓存的监控数据"""
    cache_key = f"server_{server_id}"
    current_time = time.time()

    with CACHE_LOCK:
        if not force_refresh and cache_key in MONITORING_CACHE:
            cached_data, timestamp = MONITORING_CACHE[cache_key]
            if current_time - timestamp < CACHE_DURATION:
                return cached_data

    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
        monitoring_data = zabbix_api.get_host_monitoring_data(zabbix_hostid)

        with CACHE_LOCK:
            MONITORING_CACHE[cache_key] = (monitoring_data, current_time)

        return monitoring_data
    except Exception as e:
        print(f"获取服务器 {server_id} 监控数据失败: {str(e)}")
        return {'cpu_usage': 0.0, 'memory_usage': 0.0, 'disk_usage': 0.0, 'network_in': 0.0, 'network_out': 0.0}

@monitor_bp.route('/')
@login_required
def index():
    """监控首页"""
    servers = Server.query.all()

    total_count = len(servers)
    online_count = len([s for s in servers if s.status == 'online'])

    zabbix_alerts = []
    warning_count = 0
    error_count = 0

    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
        problems = zabbix_api.get_active_problems()

        server_map_by_hostid = {}
        server_map_by_name = {}
        for s in servers:
            if s.zabbix_hostid:
                server_map_by_hostid[str(s.zabbix_hostid)] = s
                try:
                    server_map_by_hostid[int(s.zabbix_hostid)] = s
                except (ValueError, TypeError):
                    pass
            server_map_by_name[s.name] = s

        for problem in problems:
            severity = SEVERITY_MAP.get(str(problem.get('severity', '0')), 'info')

            if severity == 'warning':
                warning_count += 1
            elif severity in ['error', 'critical']:
                error_count += 1

            if len(zabbix_alerts) < 10:
                clock = problem.get('clock', 0)
                created_at = datetime.fromtimestamp(int(clock)) if clock else datetime.now()

                host_ids = problem.get('hosts', [])
                related_server = None
                if host_ids and len(host_ids) > 0:
                    host_info = host_ids[0] if isinstance(host_ids[0], dict) else {}
                    hostid = host_info.get('hostid')
                    hostname = host_info.get('host') or host_info.get('name')
                    if hostid:
                        related_server = server_map_by_hostid.get(hostid) or server_map_by_hostid.get(str(hostid))
                    if not related_server and hostname:
                        related_server = server_map_by_name.get(hostname)

                zabbix_alerts.append(ZabbixAlert(
                    id=problem.get('eventid'),
                    server=related_server,
                    alert_type='zabbix',
                    severity=severity,
                    message=problem.get('name', '未知告警'),
                    created_at=created_at,
                    source='Zabbix'
                ))

        persist_zabbix_alerts(problems)

    except Exception as e:
        print(f"从 Zabbix 获取告警统计失败: {str(e)}")
        records = AlarmRecord.query.filter_by(status=0).order_by(AlarmRecord.trigger_time.desc()).limit(10).all()
        zabbix_alerts = [alarm_record_to_zabbix_alert(r) for r in records]
        warning_count = len([a for a in zabbix_alerts if a.severity == 'warning'])
        error_count = len([a for a in zabbix_alerts if a.severity in ['error', 'critical']])

    default_data = {'cpu_usage': 0.0, 'memory_usage': 0.0, 'disk_usage': 0.0, 'network_in': 0.0, 'network_out': 0.0}
    server_monitoring_data = {server.id: default_data for server in servers}

    return render_template('monitor/index.html',
                         servers=servers,
                         server_monitoring_data=server_monitoring_data,
                         total_count=total_count,
                         online_count=online_count,
                         warning_count=warning_count,
                         error_count=error_count,
                         alerts=zabbix_alerts)

@monitor_bp.route('/api/monitoring')
def api_monitoring():
    """获取监控数据API"""
    import concurrent.futures

    servers = Server.query.all()
    servers_with_zabbix = [s for s in servers if s.zabbix_hostid]

    server_monitoring_data = {}
    MAX_WORKERS = min(10, max(1, len(servers_with_zabbix)))

    def fetch_monitoring_data(server):
        try:
            data = get_cached_monitoring_data(server.id, server.zabbix_hostid)
            return server.id, data
        except Exception:
            return server.id, {'cpu_usage': 0.0, 'memory_usage': 0.0, 'disk_usage': 0.0, 'network_in': 0.0, 'network_out': 0.0}

    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_server = {
                executor.submit(fetch_monitoring_data, server): server
                for server in servers_with_zabbix
            }

            for future in concurrent.futures.as_completed(future_to_server, timeout=5):
                server_id, data = future.result()
                server_monitoring_data[server_id] = data

        return jsonify({'success': True, 'data': server_monitoring_data, 'timestamp': time.time()})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@monitor_bp.route('/alerts')
@login_required
def alerts():
    """告警列表"""
    zabbix_alerts = []

    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
        problems = zabbix_api.get_active_problems(recent=False)

        servers = Server.query.all()
        server_map_by_hostid = {}
        server_map_by_name = {}
        for s in servers:
            if s.zabbix_hostid:
                server_map_by_hostid[str(s.zabbix_hostid)] = s
                try:
                    server_map_by_hostid[int(s.zabbix_hostid)] = s
                except (ValueError, TypeError):
                    pass
            server_map_by_name[s.name] = s

        for problem in problems:
            clock = problem.get('clock', 0)
            created_at = datetime.fromtimestamp(int(clock)) if clock else datetime.now()

            severity = SEVERITY_MAP.get(str(problem.get('severity', '0')), 'info')

            host_ids = problem.get('hosts', [])
            related_server = None
            if host_ids and len(host_ids) > 0:
                host_info = host_ids[0] if isinstance(host_ids[0], dict) else {}
                hostid = host_info.get('hostid')
                hostname = host_info.get('host') or host_info.get('name')
                if hostid:
                    related_server = server_map_by_hostid.get(hostid) or server_map_by_hostid.get(str(hostid))
                if not related_server and hostname:
                    related_server = server_map_by_name.get(hostname)

            zabbix_alerts.append(ZabbixAlert(
                id=problem.get('eventid'),
                server_id=related_server.id if related_server else None,
                server=related_server,
                alert_type='zabbix',
                severity=severity,
                message=problem.get('name', '未知告警'),
                created_at=created_at,
                processed_at=None,
                source='Zabbix'
            ))

        persist_zabbix_alerts(problems)

    except Exception as e:
        print(f"从 Zabbix 获取告警失败: {str(e)}")
        records = AlarmRecord.query.filter_by(status=0).order_by(AlarmRecord.trigger_time.desc()).all()
        zabbix_alerts = [alarm_record_to_zabbix_alert(r) for r in records]

    warnings_count = len([a for a in zabbix_alerts if a.severity == 'warning'])
    errors_count = len([a for a in zabbix_alerts if a.severity in ['error', 'critical']])

    return render_template('monitor/alerts.html',
                         alerts=zabbix_alerts,
                         warnings_count=warnings_count,
                         errors_count=errors_count)

@monitor_bp.route('/dashboard')
@login_required
def dashboard():
    """监控大屏"""
    servers = Server.query.all()
    records = AlarmRecord.query.filter_by(status=0).order_by(AlarmRecord.trigger_time.desc()).limit(10).all()
    alerts = [alarm_record_to_zabbix_alert(r) for r in records]

    online_count = len([s for s in servers if s.status == 'online'])
    warning_count = len([a for a in alerts if a.severity == 'warning'])
    error_count = len([a for a in alerts if a.severity in ['error', 'critical']])

    history_data = {'cpu_history': [], 'memory_history': [], 'timestamps': []}

    zabbix_server = None
    for server in servers:
        if server.zabbix_hostid:
            zabbix_server = server
            break

    if zabbix_server:
        try:
            zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
            history_data = zabbix_api.get_host_history_data(zabbix_server.zabbix_hostid, hours=1)
        except Exception as e:
            print(f"获取Zabbix历史数据失败: {str(e)}")

    return render_template('monitor/dashboard/index.html',
                         servers=servers,
                         alerts=alerts,
                         online_count=online_count,
                         warning_count=warning_count,
                         zabbix_url=Config.ZABBIX_URL,
                         zabbix_token=Config.ZABBIX_TOKEN,
                         error_count=error_count,
                         history_data=history_data)

@monitor_bp.route('/server_detail/<int:server_id>')
@login_required
def server_detail(server_id):
    """服务器详情"""
    try:
        server = Server.query.get_or_404(server_id)
    except Exception as e:
        print(f"获取服务器信息失败: {str(e)}")
        return "服务器信息获取失败，请稍后重试", 500

    monitoring_data = {
        'cpu_usage': 0.0, 'memory_usage': 0.0, 'disk_usage': 0.0,
        'network_in': 0.0, 'network_out': 0.0,
        'load_average_1m': 0.0, 'load_average_5m': 0.0, 'load_average_15m': 0.0,
        'uptime': 0, 'num_processes': 0, 'cpu_cores': 0,
        'system_boot_time': 0, 'available_memory': 0, 'total_memory': 0,
        'free_swap': 0, 'total_swap': 0, 'logged_in_users': 0
    }

    history_data = {'cpu_history': [], 'memory_history': [], 'timestamps': []}
    alerts = []

    if server.zabbix_hostid:
        try:
            zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
            monitoring_data = zabbix_api.get_host_monitoring_data(server.zabbix_hostid)
            history_data = zabbix_api.get_host_history_data(server.zabbix_hostid, hours=1)
            zabbix_alerts = zabbix_api.get_host_alerts(server.zabbix_hostid)

            for alert in zabbix_alerts:
                if alert.get('r_eventid'):
                    continue
                clock = alert.get('clock', 0)
                created_at = datetime.fromtimestamp(int(clock)) if clock else datetime.now()
                severity = SEVERITY_MAP.get(str(alert.get('severity', '0')), 'info')

                alerts.append(ZabbixAlert(
                    id=alert.get('eventid'),
                    server_id=server_id,
                    alert_type='zabbix',
                    severity=severity,
                    message=alert.get('name', '未知告警'),
                    created_at=created_at,
                    processed_at=None
                ))

            persist_zabbix_alerts(zabbix_alerts)

        except Exception as e:
            print(f"获取Zabbix监控数据失败: {str(e)}")

    if not alerts:
        try:
            records = AlarmRecord.query.filter_by(status=0).order_by(AlarmRecord.trigger_time.desc()).limit(20).all()
            alerts = [alarm_record_to_zabbix_alert(r) for r in records]
        except Exception as e:
            print(f"获取本地告警数据失败: {str(e)}")
            alerts = []

    try:
        return render_template('monitor/server_detail.html',
                             server=server,
                             monitoring_data=monitoring_data,
                             history_data=history_data,
                             alerts=alerts)
    except Exception as e:
        print(f"渲染模板失败: {str(e)}")
        return "页面渲染失败，请稍后重试", 500

@monitor_bp.route('/add_to_zabbix/<int:server_id>')
@login_required
def add_to_zabbix(server_id):
    """将服务器添加到Zabbix监控"""
    server = Server.query.get_or_404(server_id)

    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)

        existing_host = zabbix_api.get_host(server.ip)
        if existing_host:
            flash(f'服务器 {server.name} 已在Zabbix中监控', 'info')
            return redirect(url_for('monitor.index'))

        host_groups = zabbix_api.get_host_groups()
        templates = zabbix_api.get_templates()

        linux_group_id = None
        linux_template_id = None

        if host_groups:
            for group in host_groups:
                if group['name'] == 'Linux servers':
                    linux_group_id = group['groupid']
                    break
            if not linux_group_id and host_groups:
                linux_group_id = host_groups[0]['groupid']

        if templates:
            for template in templates:
                if template['name'] == 'Linux by Zabbix agent':
                    linux_template_id = template['templateid']
                    break
            if not linux_template_id and templates:
                linux_template_id = templates[0]['templateid']

        if not linux_group_id:
            raise Exception("无法获取Zabbix主机组")
        if not linux_template_id:
            raise Exception("无法获取Zabbix模板")

        result = zabbix_api.create_host(
            host_name=server.name,
            host_ip=server.ip,
            group_ids=[linux_group_id],
            template_ids=[linux_template_id]
        )

        if result and 'hostids' in result and result['hostids']:
            server.zabbix_hostid = result['hostids'][0]
            db.session.commit()
            flash(f'服务器 {server.name} 已成功添加到Zabbix监控', 'success')
        else:
            flash(f'添加服务器 {server.name} 到Zabbix监控失败', 'danger')
    except Exception as e:
        flash(f'添加服务器到Zabbix监控时发生错误: {str(e)}', 'danger')

    return redirect(url_for('monitor.index'))

@monitor_bp.route('/remove_from_zabbix/<int:server_id>')
@login_required
def remove_from_zabbix(server_id):
    """从Zabbix监控中移除服务器"""
    server = Server.query.get_or_404(server_id)

    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)

        if server.zabbix_hostid or server.ip:
            result = zabbix_api.delete_host(host_ip=server.ip, host_name=server.name)
            server.zabbix_hostid = None
            db.session.commit()
            flash(f'服务器 {server.name} 已从Zabbix监控中移除', 'success')
        else:
            flash(f'服务器 {server.name} 不在Zabbix监控中', 'info')

    except Exception as e:
        db.session.rollback()
        flash(f'从Zabbix监控中移除服务器时发生错误: {str(e)}', 'danger')

    return redirect(url_for('monitor.index'))

@monitor_bp.route('/test_zabbix_connection')
def test_zabbix_connection():
    """测试 Zabbix API 连接"""
    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)

        is_connected = zabbix_api.test_connection()

        if is_connected:
            host_groups = zabbix_api.get_host_groups()
            templates = zabbix_api.get_templates()

            return jsonify({
                'success': True,
                'message': 'Zabbix API 连接成功',
                'zabbix_url': Config.ZABBIX_URL,
                'host_groups_count': len(host_groups) if host_groups else 0,
                'templates_count': len(templates) if templates else 0
            })
        else:
            return jsonify({'success': False, 'message': 'Zabbix API 连接失败', 'zabbix_url': Config.ZABBIX_URL})
    except Exception as e:
        return jsonify({'success': False, 'message': f'测试连接时发生错误: {str(e)}', 'zabbix_url': Config.ZABBIX_URL})

@monitor_bp.route('/test_zabbix_page')
@login_required
def test_zabbix_page():
    """Zabbix 连接测试页面"""
    return render_template('monitor/test_zabbix.html', zabbix_url=Config.ZABBIX_URL, zabbix_token=Config.ZABBIX_TOKEN)

@monitor_bp.route('/api/zabbix_alerts')
def api_zabbix_alerts():
    """从 Zabbix API 获取活跃告警"""
    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
        problems = zabbix_api.get_active_problems(recent=False)

        servers = Server.query.all()
        server_map_by_hostid = {}
        server_map_by_name = {}
        for s in servers:
            if s.zabbix_hostid:
                server_map_by_hostid[str(s.zabbix_hostid)] = s
                try:
                    server_map_by_hostid[int(s.zabbix_hostid)] = s
                except (ValueError, TypeError):
                    pass
            server_map_by_name[s.name] = s

        alerts = []
        for problem in problems:
            clock = problem.get('clock', 0)
            created_at = datetime.fromtimestamp(int(clock)) if clock else datetime.now()
            severity = SEVERITY_MAP.get(str(problem.get('severity', '0')), 'info')

            host_ids = problem.get('hosts', [])
            server_name = '未知主机'
            if host_ids and len(host_ids) > 0:
                host_info = host_ids[0] if isinstance(host_ids[0], dict) else {}
                hostid = host_info.get('hostid')
                hostname = host_info.get('host') or host_info.get('name')
                related_server = None
                if hostid:
                    related_server = server_map_by_hostid.get(hostid) or server_map_by_hostid.get(str(hostid))
                if not related_server and hostname:
                    related_server = server_map_by_name.get(hostname)
                if related_server:
                    server_name = related_server.name

            alerts.append({
                'eventid': problem.get('eventid'),
                'name': problem.get('name', '未知告警'),
                'severity': severity,
                'clock': clock,
                'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'server_name': server_name
            })

        persist_zabbix_alerts(problems)

        return jsonify({'success': True, 'alerts': alerts, 'count': len(alerts)})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取 Zabbix 告警失败: {str(e)}', 'alerts': []})

@monitor_bp.route('/ai_analysis', methods=['POST'])
@login_required
def ai_analysis():
    """AI分析接口 — 持久化分析记录 + 邮件通知"""
    from app.utils.ai_utils import AIAnalyzer

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})

        # 配额检查
        if current_user.ai_used >= current_user.ai_quota:
            return jsonify({'success': False, 'message': 'AI分析配额不足，请联系管理员'})

        # 准备监控数据
        monitoring_data = {
            'server_data': data.get('server_data', {}),
            'cpu_usage': data.get('monitoring_data', {}).get('cpu_usage', 0),
            'memory_usage': data.get('monitoring_data', {}).get('memory_usage', 0),
            'disk_usage': data.get('monitoring_data', {}).get('disk_usage', 0),
            'network_in': data.get('monitoring_data', {}).get('network_in', 0),
            'network_out': data.get('monitoring_data', {}).get('network_out', 0),
            'load_average_1m': data.get('monitoring_data', {}).get('load_average_1m', 0),
            'load_average_5m': data.get('monitoring_data', {}).get('load_average_5m', 0),
            'load_average_15m': data.get('monitoring_data', {}).get('load_average_15m', 0),
            'num_processes': data.get('monitoring_data', {}).get('num_processes', 0),
            'logged_in_users': data.get('monitoring_data', {}).get('logged_in_users', 0),
            'available_memory': data.get('monitoring_data', {}).get('available_memory', 0),
            'total_memory': data.get('monitoring_data', {}).get('total_memory', 0),
            'total_swap': data.get('monitoring_data', {}).get('total_swap', 0),
            'free_swap': data.get('monitoring_data', {}).get('free_swap', 0)
        }

        selected_indexes = data.get('selected_alert_indexes', [])
        alerts_list = data.get('alerts', [])
        selected_alerts = []
        if selected_indexes and alerts_list:
            for index in selected_indexes:
                if index < len(alerts_list):
                    selected_alerts.append(alerts_list[index])

        monitoring_data['selected_alerts'] = selected_alerts

        # 调用AI分析
        ai_analyzer = AIAnalyzer()
        result = ai_analyzer.analyze_server_monitoring_data(
            monitoring_data,
            data.get('selected_items', []),
            data.get('analysis_type', 'summary')
        )

        # 持久化到 AIAnalysis 表
        server_id = data.get('server_id')
        analysis_content = json.dumps(monitoring_data, ensure_ascii=False)

        ai_analysis_record = AIAnalysis(
            user_id=current_user.id,
            log_content=analysis_content,
            server_id=server_id,
            analysis_type=data.get('analysis_type', 'summary'),
            conclusion=result['conclusion'],
            suggestions=json.dumps(result['suggestions']),
            confidence=result['confidence'],
            raw_response=result.get('raw_response')
        )
        db.session.add(ai_analysis_record)

        current_user.ai_used += 1
        db.session.commit()

        # 发送邮件通知
        try:
            server = Server.query.get(server_id) if server_id else None
            alarm_summary = ''
            if selected_alerts:
                for alert in selected_alerts:
                    alarm_summary += f"- {alert.get('created_at', '')}: {alert.get('message', '')}\n"
            else:
                alarm_summary = "无告警记录"

            suggestions_text = '\n'.join(
                [f"{i+1}. {s}" for i, s in enumerate(result['suggestions'])]
            ) if result['suggestions'] else '请查看详细分析'

            subject = f"[AI监控分析] {server.name if server else '未知服务器'} - {data.get('analysis_type', 'summary')}"
            body = f"""AI监控分析报告：

服务器：{server.name if server else '未知'} ({server.ip if server else '未知'})
分析类型：{data.get('analysis_type', 'summary')}
分析时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}

=== 告警内容 ===
{alarm_summary}

=== AI结论 ===
{result['conclusion']}

=== 处理建议 ===
{suggestions_text}
"""
            send_email(subject, ['admin@supome.cn'], body)
        except Exception as email_err:
            print(f"发送AI分析邮件通知失败: {str(email_err)}")

        return jsonify({'success': True, 'result': result['html_content']})

    except Exception as e:
        print(f"AI分析失败: {str(e)}")
        return jsonify({'success': False, 'message': 'AI分析失败，无法获取分析结果'})