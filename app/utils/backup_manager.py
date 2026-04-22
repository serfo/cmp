import os
import json
import time
import shutil
import threading
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


class BackupManager:
    def __init__(self, backup_dir: str = None):
        self._backup_dir = backup_dir
        self._initialized = False
        self._tasks = {}
        self._tasks_lock = threading.Lock()

    def _ensure_initialized(self):
        if self._initialized:
            return

        from app.config import Config
        self.backup_dir = self._backup_dir or Config.get('BACKUP_DIR', '/var/backup/cloud-management-platform')
        self.metadata_file = os.path.join(self.backup_dir, 'backups.json')
        self._ensure_backup_dir()
        self._ensure_metadata()
        self._initialized = True

    def _ensure_backup_dir(self):
        if not os.path.exists(self.backup_dir):
            try:
                os.makedirs(self.backup_dir, exist_ok=True)
            except Exception as e:
                print(f"创建备份目录失败: {e}")

    def _ensure_metadata(self):
        if not os.path.exists(self.metadata_file):
            self._save_metadata({})

    def _load_metadata(self) -> Dict:
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def _save_metadata(self, metadata: Dict):
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存备份元数据失败: {e}")

    def _get_server_backup_path(self, server_ip: str) -> str:
        self._ensure_initialized()
        server_path = os.path.join(self.backup_dir, server_ip)
        if not os.path.exists(server_path):
            os.makedirs(server_path, exist_ok=True)
        return server_path

    def _record_backup(self, server_ip: str, backup_type: str, paths: List[str], file_count: int, total_size: int, backup_session_dir: str = None):
        self._ensure_initialized()
        metadata = self._load_metadata()
        if server_ip not in metadata:
            metadata[server_ip] = []

        backup_path = os.path.basename(backup_session_dir) if backup_session_dir else ''
        record = {
            'id': int(time.time() * 1000),
            'timestamp': datetime.now().isoformat(),
            'type': backup_type,
            'paths': paths,
            'file_count': file_count,
            'total_size': total_size,
            'status': 'completed',
            'backup_path': backup_path
        }
        metadata[server_ip].insert(0, record)
        metadata[server_ip] = metadata[server_ip][:100]
        self._save_metadata(metadata)
        return record

    def _connect_ssh(self, server) -> Optional[Tuple]:
        if not HAS_PARAMIKO:
            return None, None

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            if hasattr(server, 'ssh_key_path') and server.ssh_key_path and os.path.exists(server.ssh_key_path):
                try:
                    key = paramiko.RSAKey.from_private_key_file(server.ssh_key_path)
                    client.connect(server.ip, port=server.port, username=server.username, pkey=key, timeout=10)
                except Exception:
                    client.connect(server.ip, port=server.port, username=server.username, password=server.password, timeout=10)
            else:
                client.connect(server.ip, port=server.port, username=server.username, password=server.password, timeout=10)

            sftp = client.open_sftp()
            return client, sftp
        except Exception as e:
            print(f"SSH连接失败 {server.ip}: {e}")
            return None, None

    def _get_file_info(self, sftp, remote_path: str) -> Optional[Dict]:
        try:
            stat = sftp.stat(remote_path)
            return {
                'size': stat.st_size,
                'mtime': stat.st_mtime,
                'is_dir': stat.st_mode & 0o170000 == 0o40000
            }
        except:
            return None

    def _download_file(self, sftp, remote_path: str, local_path: str) -> bool:
        try:
            parent_dir = os.path.dirname(local_path)
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            sftp.get(remote_path, local_path)
            return True
        except Exception as e:
            print(f"下载文件失败 {remote_path}: {e}")
            return False

    def _list_remote_directory(self, sftp, remote_path: str) -> List[Dict]:
        result = []
        try:
            for item in sftp.listdir_attr(remote_path):
                result.append({
                    'name': item.filename,
                    'path': os.path.join(remote_path, item.filename),
                    'size': item.st_size,
                    'mtime': item.st_mtime,
                    'is_dir': item.st_mode & 0o170000 == 0o40000
                })
        except Exception as e:
            print(f"列出远程目录失败 {remote_path}: {e}")
        return result

    def backup_server(self, server, paths: List[str], backup_type: str = 'full', progress_callback: Callable = None) -> Dict:
        self._ensure_initialized()
        if not HAS_PARAMIKO:
            return {'success': False, 'message': 'paramiko 未安装'}

        if not server:
            return {'success': False, 'message': '服务器不存在'}

        client, sftp = self._connect_ssh(server)
        if not client or not sftp:
            return {'success': False, 'message': f'无法连接到 {server.ip}'}

        server_backup_path = self._get_server_backup_path(server.ip)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        session_dir = os.path.join(server_backup_path, f'backup_{timestamp}')
        os.makedirs(session_dir, exist_ok=True)

        file_count = 0
        total_size = 0
        errors = []
        processed_paths = []

        def report_progress(current_file: str, file_count: int, total_size: int, status: str = 'processing'):
            if progress_callback:
                try:
                    progress_callback(current_file, file_count, total_size, status)
                except Exception:
                    pass

        try:
            for remote_path in paths:
                if not remote_path or remote_path.strip() == '':
                    continue

                remote_path = remote_path.strip()
                file_info = self._get_file_info(sftp, remote_path)

                if not file_info:
                    errors.append(f'路径不存在或无法访问: {remote_path}')
                    continue

                report_progress(remote_path, file_count, total_size, 'scanning')

                if file_info['is_dir']:
                    success_count, success_size = self._backup_directory(
                        sftp, remote_path, session_dir, server.ip, backup_type, progress_callback, file_count, total_size
                    )
                    file_count = success_count
                    total_size = success_size
                else:
                    relative_path = remote_path.lstrip('/')
                    local_path = os.path.join(session_dir, relative_path)
                    if self._download_file(sftp, remote_path, local_path):
                        file_count += 1
                        local_info = self._get_local_file_info(local_path)
                        if local_info:
                            total_size += local_info['size']
                        report_progress(remote_path, file_count, total_size, 'downloaded')
                    processed_paths.append(remote_path)

            record = self._record_backup(server.ip, backup_type, paths, file_count, total_size, session_dir)

            report_progress('完成', file_count, total_size, 'completed')

            return {
                'success': True,
                'message': f'备份完成: {file_count} 个文件, {self._format_size(total_size)}',
                'backup_id': record['id'],
                'file_count': file_count,
                'total_size': total_size,
                'backup_path': record['backup_path']
            }

        except Exception as e:
            errors.append(str(e))
            report_progress('失败', file_count, total_size, 'error')
            return {'success': False, 'message': f'备份失败: {e}'}
        finally:
            sftp.close()
            client.close()

    def _backup_directory(self, sftp, remote_dir: str, local_base: str, server_ip: str, backup_type: str, progress_callback: Callable = None, current_count: int = 0, current_size: int = 0) -> Tuple[int, int]:
        file_count = current_count
        total_size = current_size
        processed_dirs = []

        def report_progress(current_file: str, count: int, size: int, status: str = 'processing'):
            if progress_callback:
                try:
                    progress_callback(current_file, count, size, status)
                except Exception:
                    pass

        def process_directory(sftp, remote_path: str, local_path: str):
            nonlocal file_count, total_size

            if remote_path in processed_dirs:
                return
            processed_dirs.append(remote_path)

            items = self._list_remote_directory(sftp, remote_path)
            if not os.path.exists(local_path):
                os.makedirs(local_path, exist_ok=True)

            for item in items:
                item_remote_path = item['path']
                item_relative = item_remote_path.lstrip('/')
                item_local_path = os.path.join(local_base, item_relative)

                if item['is_dir']:
                    process_directory(sftp, item_remote_path, item_local_path)
                else:
                    if self._download_file(sftp, item_remote_path, item_local_path):
                        file_count += 1
                        total_size += item['size']
                        report_progress(item['name'], file_count, total_size, 'downloaded')

        process_directory(sftp, remote_dir, local_base)
        return file_count, total_size

    def start_async_backup(self, task_id: str, server, paths: List[str], backup_type: str = 'full') -> Dict:
        def run_backup():
            with self._tasks_lock:
                self._tasks[task_id] = {
                    'status': 'running',
                    'progress': 0,
                    'current_file': '',
                    'file_count': 0,
                    'total_size': 0,
                    'start_time': time.time()
                }

            def progress_callback(current_file: str, file_count: int, total_size: int, status: str):
                with self._tasks_lock:
                    if task_id in self._tasks:
                        self._tasks[task_id]['current_file'] = current_file
                        self._tasks[task_id]['file_count'] = file_count
                        self._tasks[task_id]['total_size'] = total_size
                        self._tasks[task_id]['status'] = status

            result = self.backup_server(server, paths, backup_type, progress_callback)

            with self._tasks_lock:
                if task_id in self._tasks:
                    if result['success']:
                        self._tasks[task_id]['status'] = 'completed'
                        self._tasks[task_id]['result'] = result
                    else:
                        self._tasks[task_id]['status'] = 'failed'
                        self._tasks[task_id]['error'] = result.get('message', 'Unknown error')

        thread = threading.Thread(target=run_backup, daemon=True)
        thread.start()

        return {
            'success': True,
            'task_id': task_id,
            'message': '备份任务已启动'
        }

    def get_task_status(self, task_id: str) -> Dict:
        with self._tasks_lock:
            if task_id in self._tasks:
                task = self._tasks[task_id].copy()
                task['elapsed'] = time.time() - task.get('start_time', time.time())
                return task
            return None

    def list_tasks(self) -> List[Dict]:
        with self._tasks_lock:
            return [
                {
                    'task_id': task_id,
                    **task.copy()
                }
                for task_id, task in self._tasks.items()
                if task.get('status') in ['running', 'pending']
            ]

    def remove_task(self, task_id: str) -> bool:
        with self._tasks_lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    def incremental_backup(self, server, paths: List[str], since: datetime = None) -> Dict:
        self._ensure_initialized()
        if not since:
            from datetime import timedelta
            metadata = self._load_metadata()
            server_backups = metadata.get(server.ip, [])
            if server_backups:
                last_backup_time = datetime.fromisoformat(server_backups[0]['timestamp'])
                since = last_backup_time - timedelta(days=1)
            else:
                since = datetime.now() - timedelta(days=1)

        if not HAS_PARAMIKO:
            return {'success': False, 'message': 'paramiko 未安装'}

        if not server:
            return {'success': False, 'message': '服务器不存在'}

        client, sftp = self._connect_ssh(server)
        if not client or not sftp:
            return {'success': False, 'message': f'无法连接到 {server.ip}'}

        server_backup_path = self._get_server_backup_path(server.ip)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        session_dir = os.path.join(server_backup_path, f'incremental_{timestamp}')
        os.makedirs(session_dir, exist_ok=True)

        file_count = 0
        total_size = 0
        since_ts = since.timestamp()

        try:
            for remote_path in paths:
                if not remote_path or remote_path.strip() == '':
                    continue

                remote_path = remote_path.strip()
                file_info = self._get_file_info(sftp, remote_path)

                if not file_info:
                    continue

                if file_info['is_dir']:
                    success_count, success_size = self._backup_directory_incremental(
                        sftp, remote_path, session_dir, since_ts
                    )
                    file_count += success_count
                    total_size += success_size
                else:
                    if file_info['mtime'] >= since_ts:
                        relative_path = remote_path.lstrip('/')
                        local_path = os.path.join(session_dir, relative_path)
                        if self._download_file(sftp, remote_path, local_path):
                            file_count += 1
                            total_size += file_info['size']

            record = self._record_backup(server.ip, 'incremental', paths, file_count, total_size, session_dir)
            session_backup_path = os.path.basename(session_dir)

            return {
                'success': True,
                'message': f'增量备份完成: {file_count} 个文件, {self._format_size(total_size)}',
                'backup_id': record['id'],
                'file_count': file_count,
                'total_size': total_size,
                'backup_path': session_backup_path
            }

        except Exception as e:
            return {'success': False, 'message': f'增量备份失败: {e}'}
        finally:
            sftp.close()
            client.close()

    def _backup_directory_incremental(self, sftp, remote_dir: str, local_base: str, since_ts: float) -> Tuple[int, int]:
        file_count = 0
        total_size = 0
        processed_dirs = []

        def process_directory(sftp, remote_path: str, local_path: str):
            nonlocal file_count, total_size

            if remote_path in processed_dirs:
                return
            processed_dirs.append(remote_path)

            items = self._list_remote_directory(sftp, remote_path)
            if not os.path.exists(local_path):
                os.makedirs(local_path, exist_ok=True)

            for item in items:
                item_remote_path = item['path']
                item_relative = item_remote_path.lstrip('/')
                item_local_path = os.path.join(local_base, item_relative)

                if item['is_dir']:
                    process_directory(sftp, item_remote_path, item_local_path)
                else:
                    if item['mtime'] >= since_ts:
                        if self._download_file(sftp, item_remote_path, item_local_path):
                            file_count += 1
                            total_size += item['size']

        process_directory(sftp, remote_dir, local_base)
        return file_count, total_size

    def list_backups(self, server_ip: str = None) -> List[Dict]:
        self._ensure_initialized()
        metadata = self._load_metadata()
        if server_ip:
            backups = metadata.get(server_ip, [])
            for backup in backups:
                backup['server_ip'] = server_ip
        else:
            backups = []
            for ip, server_backups in metadata.items():
                for backup in server_backups:
                    backup['server_ip'] = ip
                backups.extend(server_backups)
            backups.sort(key=lambda x: x['timestamp'], reverse=True)
        return backups

    def get_backup_stats(self, server_ip: str = None) -> Dict:
        self._ensure_initialized()
        metadata = self._load_metadata()
        total_count = 0
        total_size = 0
        server_stats = {}

        if server_ip:
            servers = [server_ip] if server_ip in metadata else []
        else:
            servers = metadata.keys()

        for ip in servers:
            backups = metadata.get(ip, [])
            server_count = len(backups)
            server_size = sum(b.get('total_size', 0) for b in backups)
            total_count += server_count
            total_size += server_size
            if not server_ip:
                server_stats[ip] = {'count': server_count, 'size': server_size}

        return {
            'total_count': total_count,
            'total_size': total_size,
            'total_size_formatted': self._format_size(total_size),
            'server_stats': server_stats if not server_ip else {}
        }

    def list_directory(self, path: str, server_ip: str = None) -> List[Dict]:
        self._ensure_initialized()
        if server_ip:
            full_path = os.path.join(self._get_server_backup_path(server_ip), path.lstrip('/'))
        else:
            full_path = path if os.path.isabs(path) else os.path.join(self.backup_dir, path.lstrip('/'))

        if not os.path.exists(full_path):
            return []

        items = []
        try:
            for item in os.listdir(full_path):
                item_path = os.path.join(full_path, item)
                stat = os.stat(item_path)
                items.append({
                    'name': item,
                    'path': os.path.relpath(item_path, self.backup_dir),
                    'size': stat.st_size,
                    'mtime': stat.st_mtime,
                    'is_dir': os.path.isdir(item_path)
                })
        except Exception as e:
            print(f"列出目录失败 {full_path}: {e}")

        return sorted(items, key=lambda x: (not x['is_dir'], x['name']))

    def preview_file(self, file_path: str, server_ip: str = None, max_lines: int = 100) -> Dict:
        self._ensure_initialized()

        if server_ip and file_path.startswith(server_ip + '/'):
            file_path = file_path[len(server_ip) + 1:]

        if server_ip:
            full_path = os.path.join(self._get_server_backup_path(server_ip), file_path.lstrip('/'))
        else:
            full_path = file_path if os.path.isabs(file_path) else os.path.join(self.backup_dir, file_path.lstrip('/'))

        if not os.path.exists(full_path):
            return {'success': False, 'message': f'文件不存在: {full_path}'}

        if os.path.isdir(full_path):
            return {'success': False, 'message': '这是一个目录'}

        try:
            stat = os.stat(full_path)
            if stat.st_size > 5 * 1024 * 1024:
                return {'success': False, 'message': '文件过大，无法预览'}

            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    lines.append(line.rstrip('\n'))

            return {
                'success': True,
                'content': lines,
                'total_lines': sum(1 for _ in open(full_path, 'r', encoding='utf-8', errors='ignore')),
                'truncated': sum(1 for _ in open(full_path, 'r', encoding='utf-8', errors='ignore')) > max_lines
            }
        except Exception as e:
            return {'success': False, 'message': f'读取文件失败: {e}'}

    def delete_backup(self, server_ip: str, backup_id: int = None, backup_path: str = None) -> Dict:
        self._ensure_initialized()
        metadata = self._load_metadata()

        if backup_id:
            backups = metadata.get(server_ip, [])
            backup_to_delete = next((b for b in backups if b['id'] == backup_id), None)
            if backup_to_delete:
                timestamp = backup_to_delete['timestamp'][:19].replace(':', '').replace('-', '')
                backup_type = backup_to_delete['type']
                path_to_delete = os.path.join(
                    self._get_server_backup_path(server_ip),
                    f'{backup_type}_{timestamp}'
                )
            else:
                return {'success': False, 'message': '备份记录不存在'}
        elif backup_path:
            path_to_delete = os.path.join(self._get_server_backup_path(server_ip), backup_path.lstrip('/'))
        else:
            return {'success': False, 'message': '未指定要删除的备份'}

        try:
            if os.path.exists(path_to_delete):
                if os.path.isdir(path_to_delete):
                    shutil.rmtree(path_to_delete)
                else:
                    os.remove(path_to_delete)

            if backup_id:
                metadata[server_ip] = [b for b in metadata.get(server_ip, []) if b['id'] != backup_id]
                self._save_metadata(metadata)

            return {'success': True, 'message': '删除成功'}
        except Exception as e:
            return {'success': False, 'message': f'删除失败: {e}'}

    def get_backup_path(self, server_ip: str = None, relative_path: str = None) -> str:
        self._ensure_initialized()
        if server_ip:
            path = self._get_server_backup_path(server_ip)
            if relative_path and relative_path.startswith(server_ip + '/'):
                relative_path = relative_path[len(server_ip) + 1:]
        else:
            path = self.backup_dir

        if relative_path:
            path = os.path.join(path, relative_path.lstrip('/'))

        return path

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def _get_local_file_info(self, local_path: str) -> Optional[Dict]:
        try:
            stat = os.stat(local_path)
            return {
                'size': stat.st_size,
                'mtime': stat.st_mtime,
                'is_dir': os.path.isdir(local_path)
            }
        except:
            return None


backup_manager = BackupManager()
