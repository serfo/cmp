from flask import Blueprint, render_template, jsonify, request, send_file, current_app
from flask_login import login_required, current_user
from app import db
from app.models.server import Server
from app.utils.backup_manager import backup_manager
from app.config import Config
import os

backup_bp = Blueprint('backup', __name__)

@backup_bp.route('/')
@login_required
def index():
    return render_template('backup/index.html')

@backup_bp.route('/restore')
@login_required
def restore():
    return render_template('backup/restore.html')

@backup_bp.route('/api/servers')
@login_required
def api_servers():
    servers = Server.query.all()
    return jsonify({
        'success': True,
        'data': [{'id': s.id, 'name': s.name, 'ip': s.ip} for s in servers]
    })

@backup_bp.route('/api/config')
@login_required
def api_config():
    backup_dir = Config.get('BACKUP_DIR', '')
    backup_interval = Config.get_int('BACKUP_INTERVAL', 0)
    return jsonify({
        'success': True,
        'data': {
            'backup_dir': backup_dir,
            'backup_interval': backup_interval
        }
    })

@backup_bp.route('/api/backup', methods=['POST'])
@login_required
def api_backup():
    try:
        data = request.get_json()
        server_id = data.get('server_id')
        paths = data.get('paths', [])
        backup_type = data.get('type', 'full')
        async_mode = data.get('async', True)

        if not server_id:
            return jsonify({'success': False, 'message': '请选择服务器'}), 400

        if not paths:
            return jsonify({'success': False, 'message': '请选择要备份的文件或目录'}), 400

        server = Server.query.get(int(server_id))
        if not server:
            return jsonify({'success': False, 'message': '服务器不存在'}), 404

        backup_dir = Config.get('BACKUP_DIR')
        if not backup_dir:
            return jsonify({'success': False, 'message': 'BACKUP_DIR 未配置'}), 400

        if async_mode:
            import uuid
            task_id = str(uuid.uuid4())[:8]
            result = backup_manager.start_async_backup(task_id, server, paths, backup_type)
            return jsonify(result)
        else:
            if backup_type == 'incremental':
                result = backup_manager.incremental_backup(server, paths)
            else:
                result = backup_manager.backup_server(server, paths, 'full')
            return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"备份失败: {str(e)}")
        return jsonify({'success': False, 'message': f'备份失败: {str(e)}'}), 500

@backup_bp.route('/api/backup/status/<task_id>')
@login_required
def api_backup_status(task_id):
    status = backup_manager.get_task_status(task_id)
    if status is None:
        return jsonify({'success': False, 'message': '任务不存在或已完成'}), 404
    return jsonify({'success': True, 'data': status})

@backup_bp.route('/api/backup/tasks')
@login_required
def api_backup_tasks():
    tasks = backup_manager.list_tasks()
    return jsonify({'success': True, 'data': tasks})

@backup_bp.route('/api/list')
@login_required
def api_list():
    server_ip = request.args.get('server_ip')
    backups = backup_manager.list_backups(server_ip)
    return jsonify({
        'success': True,
        'data': backups
    })

@backup_bp.route('/api/stats')
@login_required
def api_stats():
    server_ip = request.args.get('server_ip')
    stats = backup_manager.get_backup_stats(server_ip)
    return jsonify({
        'success': True,
        'data': stats
    })

@backup_bp.route('/api/files')
@login_required
def api_files():
    path = request.args.get('path', '')
    server_ip = request.args.get('server_ip')

    if server_ip:
        items = backup_manager.list_directory(path, server_ip)
    elif path:
        items = backup_manager.list_directory(path)
    else:
        items = backup_manager.list_directory('')

    return jsonify({
        'success': True,
        'data': items
    })

@backup_bp.route('/api/preview', methods=['POST'])
@login_required
def api_preview():
    data = request.get_json()
    file_path = data.get('path')
    server_ip = data.get('server_ip')
    max_lines = data.get('max_lines', 100)

    if not file_path:
        return jsonify({'success': False, 'message': '请指定文件路径'}), 400

    result = backup_manager.preview_file(file_path, server_ip, max_lines)
    return jsonify(result)

@backup_bp.route('/api/download')
@login_required
def api_download():
    file_path = request.args.get('path')
    server_ip = request.args.get('server_ip')

    if not file_path:
        return jsonify({'success': False, 'message': '请指定文件路径'}), 400

    if server_ip:
        full_path = backup_manager.get_backup_path(server_ip, file_path)
    else:
        full_path = file_path if os.path.isabs(file_path) else os.path.join(Config.get('BACKUP_DIR', ''), file_path.lstrip('/'))

    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': '文件不存在'}), 404

    if os.path.isdir(full_path):
        return jsonify({'success': False, 'message': '不支持下载目录'}), 400

    try:
        return send_file(
            full_path,
            as_attachment=True,
            download_name=os.path.basename(full_path)
        )
    except Exception as e:
        return jsonify({'success': False, 'message': f'下载失败: {str(e)}'}), 500

@backup_bp.route('/api/download-directory', methods=['POST'])
@login_required
def api_download_directory():
    data = request.get_json()
    dir_path = data.get('path')
    server_ip = data.get('server_ip')

    if not dir_path:
        return jsonify({'success': False, 'message': '请指定目录路径'}), 400

    if server_ip:
        full_path = backup_manager.get_backup_path(server_ip, dir_path)
    else:
        full_path = dir_path if os.path.isabs(dir_path) else os.path.join(Config.get('BACKUP_DIR', ''), dir_path.lstrip('/'))

    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': '目录不存在'}), 404

    if not os.path.isdir(full_path):
        return jsonify({'success': False, 'message': '路径不是目录'}), 400

    import tarfile
    import io

    try:
        memory_file = io.BytesIO()
        with tarfile.open(fileobj=memory_file, mode='w:gz') as tar:
            tar.add(full_path, arcname=os.path.basename(full_path))
        memory_file.seek(0)

        return send_file(
            memory_file,
            mimetype='application/gzip',
            as_attachment=True,
            download_name=f'{os.path.basename(full_path)}.tar.gz'
        )
    except Exception as e:
        return jsonify({'success': False, 'message': f'打包失败: {str(e)}'}), 500

@backup_bp.route('/api/delete', methods=['POST'])
@login_required
def api_delete():
    data = request.get_json()
    server_ip = data.get('server_ip')
    backup_id = data.get('backup_id')
    backup_path = data.get('backup_path')

    if not server_ip:
        return jsonify({'success': False, 'message': '请指定服务器IP'}), 400

    result = backup_manager.delete_backup(server_ip, backup_id, backup_path)
    return jsonify(result)

@backup_bp.route('/api/remote-path', methods=['GET'])
@login_required
def api_remote_path():
    server_id = request.args.get('server_id')
    if not server_id:
        return jsonify({'success': False, 'message': '请指定服务器'}), 400

    server = Server.query.get(int(server_id))
    if not server:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404

    try:
        from app.utils.ssh_utils import SSHClient
        ssh = SSHClient(server.ip, server.port, server.username, password=server.password, key_path=getattr(server, 'ssh_key_path', None))

        if not ssh.connect():
            return jsonify({'success': False, 'message': f'无法连接到 {server.ip}'}), 500

        stdin, stdout, stderr = ssh.client.exec_command('ls -la /', timeout=10)
        output = stdout.read().decode('utf-8', errors='ignore')

        paths = []
        for line in output.split('\n')[1:]:
            parts = line.split()
            if len(parts) >= 9:
                item_name = parts[-1]
                if item_name not in ['.', '..']:
                    item_path = '/' + item_name
                    paths.append({'name': item_name, 'path': item_path, 'is_dir': line.startswith('d')})

        ssh.close()
        return jsonify({'success': True, 'data': paths})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取路径失败: {str(e)}'}), 500

@backup_bp.route('/api/remote-files', methods=['GET'])
@login_required
def api_remote_files():
    server_id = request.args.get('server_id')
    path = request.args.get('path', '/')

    if not server_id:
        return jsonify({'success': False, 'message': '请指定服务器'}), 400

    server = Server.query.get(int(server_id))
    if not server:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404

    try:
        from app.utils.ssh_utils import SSHClient
        ssh = SSHClient(server.ip, server.port, server.username, password=server.password, key_path=getattr(server, 'ssh_key_path', None))

        if not ssh.connect():
            return jsonify({'success': False, 'message': f'无法连接到 {server.ip}'}), 500

        safe_path = path.replace('"', "'").replace(';', '').replace('&', '')
        stdin, stdout, stderr = ssh.client.exec_command(f'ls -la "{safe_path}"', timeout=10)
        output = stdout.read().decode('utf-8', errors='ignore')

        items = []
        for line in output.split('\n')[1:]:
            parts = line.split()
            if len(parts) >= 9:
                item_name = parts[-1]
                if item_name not in ['.', '..']:
                    item_path = os.path.join(path, item_name).replace('\\', '/')
                    is_dir = line.startswith('d')
                    size = int(parts[4]) if parts[4].isdigit() else 0
                    items.append({'name': item_name, 'path': item_path, 'is_dir': is_dir, 'size': size})

        ssh.close()
        return jsonify({'success': True, 'data': items})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取文件列表失败: {str(e)}'}), 500
