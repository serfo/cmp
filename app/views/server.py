from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.server import Server
from app.utils.ssh_utils import SSHClient
import threading
import time
import paramiko
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.backends import default_backend
import cryptography
import cryptography.hazmat.primitives.serialization as serialization
import hashlib

# 创建蓝图
server_bp = Blueprint('server', __name__)

@server_bp.route('/')
@login_required
def index():
    """服务器列表"""
    servers = Server.query.all()
    return render_template('server/index.html', servers=servers)

@server_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """添加服务器"""
    if request.method == 'POST':
        name = request.form['name']
        ip = request.form['ip']
        port = int(request.form['port'])
        username = request.form['username']
        password = request.form['password']
        
        if Server.query.filter_by(ip=ip).first():
            flash('该IP地址已存在', 'danger')
            return redirect(url_for('server.add'))
        
        ssh_client = SSHClient(ip, port, username, password)
        if ssh_client.connect():
            server_info = ssh_client.get_server_info()
            ssh_client.close()
        else:
            server_info = None
            ssh_client.close()
        
        new_server = Server(
            name=name,
            ip=ip,
            port=port,
            username=username,
            password=password,
            os=server_info.get('os') if server_info else None,
            cpu=server_info.get('cpu') if server_info else None,
            memory=server_info.get('memory') if server_info else None,
            disk=server_info.get('disk') if server_info else None,
            status='online' if server_info else 'offline'
        )
        
        db.session.add(new_server)
        db.session.commit()
        
        flash('服务器添加成功', 'success')
        return redirect(url_for('server.index'))
    
    return render_template('server/add.html')

@server_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    """编辑服务器"""
    server = Server.query.get_or_404(id)
    
    if request.method == 'POST':
        server.name = request.form['name']
        server.ip = request.form['ip']
        server.port = int(request.form['port'])
        server.username = request.form['username']
        
        if request.form['password']:
            server.password = request.form['password']
        
        ssh_client = SSHClient(server.ip, server.port, server.username, server.password)
        if ssh_client.connect():
            server_info = ssh_client.get_server_info()
            ssh_client.close()
            
            server.os = server_info.get('os')
            server.cpu = server_info.get('cpu')
            server.memory = server_info.get('memory')
            server.disk = server_info.get('disk')
            server.status = 'online'
        else:
            server.status = 'offline'
            ssh_client.close()
        
        db.session.commit()
        
        flash('服务器更新成功', 'success')
        return redirect(url_for('server.index'))
    
    return render_template('server/edit.html', server=server)

@server_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    """删除服务器"""
    from app.config import Config
    from app.utils.zabbix_api import ZabbixAPI
    from app.utils.ssh_utils import SSHClient

    server = Server.query.get_or_404(id)
    server_name = server.name
    server_ip = server.ip

    error_messages = []
    success_messages = []

    try:
        zabbix_api = ZabbixAPI(Config.ZABBIX_URL, Config.ZABBIX_TOKEN)
        ssh_client = SSHClient(server.ip, server.port, server.username, server.password)

        if server.zabbix_hostid or server.ip:
            try:
                result = zabbix_api.delete_host(host_ip=server.ip, host_name=server.name)
                if result:
                    success_messages.append('已从Zabbix服务器移除')
                else:
                    success_messages.append('Zabbix中主机已不存在或已移除')
            except Exception as e:
                error_messages.append(f'从Zabbix移除失败: {str(e)}')

        if ssh_client.connect():
            commands = [
                ("停止Zabbix Agent服务", "systemctl stop zabbix-agent 2>/dev/null || service zabbix-agent stop 2>/dev/null || true"),
                ("禁用Zabbix Agent服务", "systemctl disable zabbix-agent 2>/dev/null || chkconfig --del zabbix-agent 2>/dev/null || true"),
                ("删除Zabbix Agent程序", "rm -f /usr/local/zabbix_agent/sbin/zabbix_agentd /usr/local/zabbix_agent/sbin/zabbix_agentd /usr/sbin/zabbix_agentd 2>/dev/null || true"),
                ("删除Zabbix配置文件", "rm -f /usr/local/zabbix_agent/etc/zabbix_agentd.conf 2>/dev/null || true"),
                ("删除Zabbix Agent目录", "rm -rf /usr/local/zabbix_agent /etc/zabbix_agentd.conf.d 2>/dev/null || true"),
                ("删除Zabbix用户", "userdel zabbix 2>/dev/null || true"),
                ("备份rsyslog配置", "cp /etc/rsyslog.conf /etc/rsyslog.conf.bak 2>/dev/null || true"),
                ("移除rsyslog中的Zabbix配置", "sed -i '/imfile.*zabbix/d' /etc/rsyslog.conf 2>/dev/null || sed -i '/module.*imfile/d' /etc/rsyslog.conf 2>/dev/null || true"),
                ("重启rsyslog服务", "systemctl restart rsyslog 2>/dev/null || service rsyslog restart 2>/dev/null || true"),
            ]

            for desc, cmd in commands:
                result = ssh_client.execute_command(cmd, timeout=30)
                if result and result.get('exit_code') == 0:
                    success_messages.append(f'{desc}成功')
                else:
                    error_messages.append(f'{desc}失败')

            ssh_client.close()
        else:
            error_messages.append('无法连接服务器，部分清理操作未能执行')

        db.session.delete(server)
        db.session.commit()

        success_messages.append(f'服务器 {server_name} ({server_ip}) 已从数据库删除')

        for msg in success_messages:
            flash(msg, 'success')
        for msg in error_messages:
            flash(msg, 'warning')

    except Exception as e:
        db.session.rollback()
        flash(f'删除服务器 {server_name} 失败: {str(e)}', 'danger')

    return redirect(url_for('server.index'))

@server_bp.route('/test_ssh/<int:id>', methods=['POST'])
@login_required
def test_ssh(id):
    """测试SSH连接"""
    server = Server.query.get_or_404(id)
    ssh_client = SSHClient(server.ip, server.port, server.username, server.password)
    success = ssh_client.connect()
    ssh_client.close()
    
    if success:
        return jsonify({'success': True, 'message': '服务器连接成功'})
    else:
        return jsonify({'success': False, 'message': '服务器连接失败'})

@server_bp.route('/refresh/<int:id>')
@login_required
def refresh(id):
    """刷新服务器信息"""
    server = Server.query.get_or_404(id)
    
    ssh_client = SSHClient(server.ip, server.port, server.username, server.password)
    if ssh_client.connect():
        server_info = ssh_client.get_server_info()
        ssh_client.close()
        
        server.os = server_info.get('os')
        server.cpu = server_info.get('cpu')
        server.memory = server_info.get('memory')
        server.disk = server_info.get('disk')
        server.status = 'online'
        db.session.commit()
        flash('服务器信息刷新成功', 'success')
    else:
        server.status = 'offline'
        ssh_client.close()
        db.session.commit()
        flash('服务器连接失败', 'danger')
    
    return redirect(url_for('server.index'))

@server_bp.route('/refresh-all')
@login_required
def refresh_all():
    """刷新所有服务器信息 - 优化版"""
    logs = []
    
    try:
        servers = Server.query.all()
        logs.append(f"开始刷新 {len(servers)} 台服务器...")
        
        max_concurrent = min(len(servers), 10)
        
        def refresh_single(server):
            try:
                ssh = SSHClient(server.ip, server.port, server.username, server.password)
                if ssh.connect():
                    info = ssh.get_server_info()
                    ssh.close()
                    return {
                        'server_id': server.id,
                        'server_name': server.name,
                        'success': True,
                        'info': info
                    }
                else:
                    return {
                        'server_id': server.id,
                        'server_name': server.name,
                        'success': False
                    }
            except Exception as e:
                return {
                    'server_id': server.id,
                    'server_name': server.name,
                    'success': False,
                    'error': str(e)
                }
        
        with ThreadPoolExecutor(max_workers=max_concurrent) as exec:
            future_to_server = {exec.submit(refresh_single, s): s for s in servers}
            
            completed = 0
            for future in as_completed(future_to_server):
                result = future.result()
                completed += 1
                if result['success']:
                    logs.append(f"✓ [{completed}/{len(servers)}] {result['server_name']} 刷新成功")
                    server = Server.query.get(result['server_id'])
                    if server and result['info']:
                        server.os = result['info'].get('os')
                        server.cpu = result['info'].get('cpu')
                        server.memory = result['info'].get('memory')
                        server.disk = result['info'].get('disk')
                        server.status = 'online'
                else:
                    logs.append(f"✗ [{completed}/{len(servers)}] {result['server_name']} 离线")
                    server = Server.query.get(result['server_id'])
                    if server:
                        server.status = 'offline'
        
        db.session.commit()
        logs.append(f"完成！成功 {len([l for l in logs if '✓' in l])}/{len(servers)} 台")
        
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        logs.append(f"错误: {str(e)}")
        return jsonify({'success': False, 'message': str(e), 'logs': logs})

@server_bp.route('/api/ssh/keys/generate', methods=['POST'])
@login_required
def generate_ssh_key():
    """生成新的SSH密钥对"""
    try:
        key_type = request.json.get('type', 'rsa')
        key_bits = int(request.json.get('bits', 2048))
        comment = request.json.get('comment', 'deploy@cloud-management')
        
        if key_type == 'ed25519':
            private_bytes = ed25519.Ed25519PrivateKey.generate()
            private_pem = private_bytes.private_bytes(
                encoding=cryptography.hazmat.primitives.serialization.Encoding.PEM,
                format=cryptography.hazmat.primitives.serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=cryptography.hazmat.primitives.serialization.NoEncryption()
            )
            public_bytes = private_bytes.public_key().public_bytes(
                encoding=cryptography.hazmat.primitives.serialization.Encoding.OpenSSH,
                format=cryptography.hazmat.primitives.serialization.PublicFormat.OpenSSH
            )
            private_key = private_pem.decode('utf-8')
            public_key = f"{public_bytes.decode('utf-8')} {comment}"
            public_key_raw = private_bytes.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            fingerprint = hashlib.md5(public_key_raw).hexdigest()
        elif key_type == 'rsa':
            key = paramiko.RSAKey.generate(key_bits)
            private_key = key.get_private_key().decode('utf-8')
            public_key = f"{key.get_name()} {key.get_base64()} {comment}"
            fingerprint = key.get_fingerprint().hex()
        else:
            key = paramiko.RSAKey.generate(key_bits)
            private_key = key.get_private_key().decode('utf-8')
            public_key = f"{key.get_name()} {key.get_base64()} {comment}"
            fingerprint = key.get_fingerprint().hex()
        
        keys_dir = os.path.expanduser('~/.ssh/cloud-management')
        os.makedirs(keys_dir, exist_ok=True)
        
        key_path = os.path.join(keys_dir, f'id_{key_type}_{int(time.time())}')
        with open(key_path, 'w') as f:
            f.write(private_key)
        os.chmod(key_path, 0o600)
        
        pub_path = f"{key_path}.pub"
        with open(pub_path, 'w') as f:
            f.write(public_key)
        
        return jsonify({
            'success': True,
            'key_type': key_type,
            'private_key': private_key,
            'public_key': public_key,
            'fingerprint': fingerprint,
            'key_path': key_path
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@server_bp.route('/api/ssh/deploy', methods=['POST'])
@login_required
def deploy_ssh_key():
    """一键部署SSH密钥到服务器"""
    try:
        pub_key = request.json.get('public_key')
        server_ids = request.json.get('server_ids', [])
        
        if not pub_key:
            return jsonify({'success': False, 'message': '公钥不能为空'})
        
        if server_ids:
            servers = Server.query.filter(Server.id.in_(server_ids)).all()
        else:
            servers = Server.query.all()
        
        if not servers:
            return jsonify({'success': False, 'message': '没有找到服务器'})
        
        logs = []
        success_count = 0
        fail_count = 0
        
        def deploy_to_server(server):
            try:
                ssh = SSHClient(server.ip, server.port, server.username, server.password)
                if not ssh.connect():
                    return {
                        'server_id': server.id,
                        'server_name': server.name,
                        'success': False,
                        'error': '连接失败'
                    }
                
                commands = [
                    f'mkdir -p ~/.ssh',
                    f'echo "{pub_key}" >> ~/.ssh/authorized_keys',
                    f'chmod 700 ~/.ssh',
                    f'chmod 600 ~/.ssh/authorized_keys'
                ]
                
                all_success = True
                for cmd in commands:
                    result = ssh.execute_command(cmd, timeout=10)
                    if result and result.get('exit_code') != 0:
                        all_success = False
                        break
                
                ssh.close()
                return {
                    'server_id': server.id,
                    'server_name': server.name,
                    'success': all_success,
                    'error': None if all_success else '命令执行失败'
                }
            except Exception as e:
                return {
                    'server_id': server.id,
                    'server_name': server.name,
                    'success': False,
                    'error': str(e)
                }
        
        max_concurrent = min(len(servers), 10)
        with ThreadPoolExecutor(max_workers=max_concurrent) as exec:
            future_to_server = {exec.submit(deploy_to_server, s): s for s in servers}
            
            for future in as_completed(future_to_server):
                result = future.result()
                if result['success']:
                    success_count += 1
                    logs.append(f"✓ {result['server_name']} 部署成功")
                else:
                    fail_count += 1
                    logs.append(f"✗ {result['server_name']} 部署失败: {result.get('error', '未知错误')}")
        
        return jsonify({
            'success': True,
            'total': len(servers),
            'success_count': success_count,
            'fail_count': fail_count,
            'logs': logs
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@server_bp.route('/api/ssh/test-connection', methods=['POST'])
@login_required
def test_ssh_connection():
    """测试SSH连接"""
    try:
        server_id = request.json.get('server_id')
        
        if server_id:
            server = Server.query.get_or_404(server_id)
            
            ssh = SSHClient(server.ip, server.port, server.username, server.password)
            success = ssh.connect()
            message = "连接成功" if success else "连接失败"
            ssh.close()
            
            return jsonify({
                'success': success,
                'message': message,
                'server': server.name
            })
        else:
            return jsonify({'success': False, 'message': '请指定服务器ID'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# 定时同步服务器状态的函数
def sync_server_status(app):
    """定时同步服务器状态 - 优化版"""
    while True:
        with app.app_context():
            try:
                servers = Server.query.all()
                if not servers:
                    time.sleep(60)
                    continue
                
                max_concurrent = min(len(servers), 10)
                
                def check_single(server):
                    try:
                        ssh = SSHClient(server.ip, server.port, server.username, server.password)
                        if ssh.connect(timeout=5):
                            ssh.close()
                            return server.id, 'online'
                        else:
                            return server.id, 'offline'
                    except:
                        return server.id, 'offline'
                
                with ThreadPoolExecutor(max_workers=max_concurrent) as exec:
                    futures = [exec.submit(check_single, s) for s in servers]
                    for future in as_completed(futures):
                        server_id, status = future.result()
                        server = Server.query.get(server_id)
                        if server:
                            server.status = status

                db.session.commit()
            except Exception as e:
                pass
        time.sleep(120)

def start_sync_thread(app):
    """启动定时同步线程"""
    sync_thread = threading.Thread(target=sync_server_status, args=(app,), daemon=True)
    sync_thread.start()
    # alert_thread = threading.Thread(target=sync_zabbix_alerts, args=(app,), daemon=True)
    # alert_thread.start()

def sync_zabbix_alerts(app):
    """定时从Zabbix API同步告警 - 已弃用"""
    pass

def start_sync_thread(app):
    """启动定时同步线程"""
    sync_thread = threading.Thread(target=sync_server_status, args=(app,), daemon=True)
    sync_thread.start()