from flask import Flask, jsonify, request, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_principal import Principal
from app.config import Config
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime

# 初始化扩展
db = SQLAlchemy()
login_manager = LoginManager()
principals = Principal()

# 初始化APScheduler
scheduler = BackgroundScheduler()

# 从用户ID加载用户的回调函数
@login_manager.user_loader
def load_user(user_id):
    from app.models.user import User
    return User.query.get(int(user_id))

def create_app(config_class=Config):
    """创建Flask应用实例"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 添加自定义Jinja2过滤器
    def timestamp_to_datetime(timestamp):
        """将Unix时间戳转换为日期时间格式"""
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    app.jinja_env.filters['timestamp_to_datetime'] = timestamp_to_datetime

    # 错误处理器
    @app.errorhandler(403)
    def forbidden(e):
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'message': '无权限访问'}), 403
        return render_template('error/403.html'), 403

    @app.errorhandler(401)
    def unauthorized(e):
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        return redirect(url_for('auth.login'))

    @app.errorhandler(404)
    def not_found(e):
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'message': '页面不存在'}), 404
        return render_template('error/404.html'), 404

    # 用户权限访问控制
    @app.before_request
    def check_user_access():
        from flask_login import current_user
        from flask import redirect, url_for

        # 不需要检查的路径
        exempt_urls = [
            '/auth/login',
            '/auth/logout',
            '/auth/register',
            '/static/',
            '/favicon.ico'
        ]

        # 检查是否在豁免列表中
        for url in exempt_urls:
            if request.path.startswith(url):
                return None

        # 如果用户未登录，放行（由 login_required 处理）
        if not current_user.is_authenticated:
            return None

        # 如果是 user 角色，限制访问管理页面
        if current_user.role == 'user':
            # user 只能访问 /static/monitor/ 路径
            if request.path.startswith('/static/monitor/'):
                return None

            # 其他所有管理页面都拒绝，重定向到监控面板
            scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
            host = request.headers.get('X-Forwarded-Host', request.host)
            return redirect(f'{scheme}://{host}/static/monitor/dashboard/index.html')

        # admin 角色放行
        return None

    # 从 config.json 加载初始数据库配置
    Config.init_db_config(app)

    # 初始化扩展
    db.init_app(app)
    login_manager.init_app(app)
    principals.init_app(app)

    # 从数据库加载配置并写入环境变量
    with app.app_context():
        Config.init_app_config(app)
        # 把数据库配置同步到 app.config（Flask-Mail 等扩展需要从 app.config 读取）
        import os
        for key in ['MAIL_SERVER', 'MAIL_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD',
                     'MAIL_USE_TLS', 'MAIL_USE_SSL', 'MAIL_DEFAULT_SENDER']:
            if key in os.environ and key not in app.config:
                val = os.environ[key]
                if key in ['MAIL_PORT']:
                    app.config[key] = int(val) if val else 25
                elif key in ['MAIL_USE_TLS', 'MAIL_USE_SSL']:
                    app.config[key] = val.lower() == 'true'
                else:
                    app.config[key] = val

    if not app.config.get('SECRET_KEY') or app.config.get('SECRET_KEY') == 'None':
        app.config['SECRET_KEY'] = 'dev-secret-key-for-session'
        Config.SECRET_KEY = 'dev-secret-key-for-session'

    # 初始化邮件服务
    from app.utils.email_utils import init_mail
    init_mail(app)
    
    # 注册蓝图
    from app.views.auth import auth_bp
    from app.views.server import server_bp, start_sync_thread
    from app.views.monitor import monitor_bp
    from app.views.automation import automation_bp
    from app.views.log import log_bp
    from app.views.backup import backup_bp
    from app.views.config import config_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(server_bp, url_prefix='/server')
    app.register_blueprint(monitor_bp, url_prefix='/monitor')
    app.register_blueprint(automation_bp, url_prefix='/automation')
    app.register_blueprint(log_bp, url_prefix='/log')
    app.register_blueprint(backup_bp, url_prefix='/backup')
    app.register_blueprint(config_bp, url_prefix='/config')
    
    # API蓝图
    from app.views.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api/v1')
    
    # 启动定时同步服务器状态的线程
    start_sync_thread(app)

    # 启动APScheduler
    # 延迟加载任务，避免在数据库迁移前访问数据库
    if not scheduler.running:
        scheduler.start()

    # 注册告警轮询定时任务：每2分钟轮询Zabbix，新告警自动AI分析+邮件
    from app.views.monitor import poll_zabbix_alerts
    scheduler.add_job(
        func=poll_zabbix_alerts,
        args=[app],
        trigger='interval',
        minutes=2,
        id='poll_zabbix_alerts',
        replace_existing=True
    )
    
    return app

def execute_task(app, task_id):
    """执行定时任务"""
    with app.app_context():
        from app.models.task import Task, TaskLog
        from app.models.server import Server
        from app.utils.ansible_api import AnsibleAPI
        import json
        
        task = Task.query.get(task_id)
        if task:
            # 更新任务状态
            task.status = 'running'
            task.last_executed_at = datetime.utcnow()
            db.session.commit()
            
            # 记录开始执行日志
            log = TaskLog(
                task_id=task.id,
                status='running',
                message='任务开始执行'
            )
            db.session.add(log)
            db.session.commit()
            
            # 获取当前日志记录的ID，用于后续更新
            current_log_id = log.id
            
            # 这里添加实际的任务执行逻辑
            try:
                # 解析目标服务器
                target_servers = json.loads(task.target_servers)
                
                # 查找对应的服务器对象
                servers = Server.query.filter(Server.ip.in_(target_servers)).all()
                
                # 创建AnsibleAPI实例
                ansible_api = AnsibleAPI()
                
                # 生成主机清单
                ansible_api.generate_hosts_from_db(servers)
                
                # 执行命令
                result = ansible_api.run_command('all_servers', task.command)
                
                # 更新之前创建的日志记录，而不是创建新记录
                log = TaskLog.query.get(current_log_id)
                if log:
                    log.status = 'completed'
                    log.message = '任务执行成功'
                    log.output = result['stdout'] + result['stderr']
                    db.session.commit()
                
                # 更新任务状态
                task.status = 'completed'
                task.last_executed_at = datetime.utcnow()
                db.session.commit()
                print(f"任务 {task.id} - {task.name} 执行完成")
            except Exception as e:
                # 更新之前创建的日志记录，而不是创建新记录
                log = TaskLog.query.get(current_log_id)
                if log:
                    log.status = 'failed'
                    log.message = f'任务执行失败: {str(e)}'
                    log.output = str(e)
                    db.session.commit()
                
                # 更新任务状态
                task.status = 'failed'
                task.last_executed_at = datetime.utcnow()
                db.session.commit()
                print(f"任务 {task.id} - {task.name} 执行失败: {str(e)}")
            finally:
                # 清理资源
                ansible_api.cleanup_temp_hosts()
