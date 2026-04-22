import subprocess
import json
import re
import tempfile
import os
import glob

class AnsibleAPI:
    """Ansible API封装 - 支持私网部署管理公网服务器场景"""
    
    # 跨网络SSH连接参数优化
    SSH_COMMON_ARGS_PRIVATE_TO_PUBLIC = (
        "-o StrictHostKeyChecking=no "
        "-o UserKnownHostsFile=/dev/null "
        "-o ConnectTimeout=30 "
        "-o ServerAliveInterval=60 "
        "-o ServerAliveCountMax=3 "
        "-o TCPKeepAlive=yes "
        "-o PreferredAuthentications=publickey,password "
        "-o LogLevel=ERROR"
    )
    
    SSH_COMMON_ARGS_DEFAULT = (
        "-o StrictHostKeyChecking=no "
        "-o UserKnownHostsFile=/dev/null"
    )
    
    def __init__(self, hosts_path=None, ssh_key_path=None, deployment_mode='auto'):
        """
        初始化Ansible API
        
        Args:
            hosts_path: Ansible主机清单路径
            ssh_key_path: SSH密钥路径
            deployment_mode: 部署模式
                - 'auto': 自动检测网络环境（默认）
                - 'private_to_public': 明确指定私网部署管理公网服务器
                - 'same_network': 同网络环境部署
        """
        self.hosts_path = hosts_path
        self.temp_hosts_path = None
        self.ssh_key_path = ssh_key_path or self._find_latest_ssh_key()
        self.deployment_mode = deployment_mode
        self.ssh_common_args = self.SSH_COMMON_ARGS_PRIVATE_TO_PUBLIC if deployment_mode == 'private_to_public' else self.SSH_COMMON_ARGS_DEFAULT
    
    def _is_private_ip(self, ip):
        """检测是否为私网IP地址"""
        private_ranges = [
            ('10.0.0.0', '10.255.255.255'),
            ('172.16.0.0', '172.31.255.255'),
            ('192.168.0.0', '192.168.255.255'),
        ]
        
        try:
            ip_int = self._ip_to_int(ip)
            for start, end in private_ranges:
                if self._ip_to_int(start) <= ip_int <= self._ip_to_int(end):
                    return True
        except:
            pass
        return False
    
    def _ip_to_int(self, ip):
        """IP地址转换为整数"""
        parts = ip.split('.')
        return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])
    
    def _find_latest_ssh_key(self):
        """查找最新的SSH密钥文件"""
        key_paths = [
            os.path.expanduser('~/.ssh/cloud-management/id_ed25519_*'),
            os.path.expanduser('~/.ssh/cloud-management/id_rsa_*'),
            os.path.expanduser('~/.ssh/id_ed25519'),
            os.path.expanduser('~/.ssh/id_rsa'),
        ]
        
        for pattern in key_paths:
            keys = glob.glob(pattern)
            if keys:
                # 返回最新的密钥文件
                return max(keys, key=os.path.getmtime)
        
        return None
    
    def generate_hosts_from_db(self, servers):
        """从数据库服务器列表生成Ansible主机清单
        
        优化说明：
        - 根据部署模式选择合适的SSH连接参数
        - 私网到公网场景使用增强型连接参数
        - 优先使用密码认证（需要服务器端安装sshpass工具），密钥作为备选
        """
        temp_dir = tempfile.gettempdir()
        self.temp_hosts_path = os.path.join(temp_dir, 'ansible_db_hosts')
        
        with open(self.temp_hosts_path, 'w') as f:
            f.write('[all_servers]\n')
            for server in servers:
                server_ip = server.ip
                is_private_ip = self._is_private_ip(server_ip)
                
                if self.deployment_mode == 'auto':
                    if not is_private_ip:
                        current_ssh_args = self.SSH_COMMON_ARGS_PRIVATE_TO_PUBLIC
                    else:
                        current_ssh_args = self.SSH_COMMON_ARGS_DEFAULT
                elif self.deployment_mode == 'private_to_public':
                    current_ssh_args = self.SSH_COMMON_ARGS_PRIVATE_TO_PUBLIC
                else:
                    current_ssh_args = self.SSH_COMMON_ARGS_DEFAULT
                
                if server.password:
                    f.write(f"{server_ip} ansible_port={server.port} ansible_user={server.username} ansible_password={server.password} ansible_ssh_common_args='{current_ssh_args}'\n")
                elif self.ssh_key_path and os.path.exists(self.ssh_key_path):
                    f.write(f"{server_ip} ansible_port={server.port} ansible_user={server.username} ansible_ssh_private_key_file={self.ssh_key_path} ansible_ssh_common_args='{current_ssh_args}'\n")
                else:
                    f.write(f"{server_ip} ansible_port={server.port} ansible_user={server.username} ansible_ssh_common_args='{current_ssh_args}'\n")
        
        self.hosts_path = self.temp_hosts_path
        return self.temp_hosts_path
    
    def cleanup_temp_hosts(self):
        """清理临时主机清单文件"""
        if self.temp_hosts_path and os.path.exists(self.temp_hosts_path):
            os.remove(self.temp_hosts_path)
            self.temp_hosts_path = None
    
    def run_command(self, hosts, command, use_raw=False, auto_fallback=True):
        """执行命令
        
        Args:
            hosts: 主机组或主机
            command: 要执行的命令
            use_raw: 是否使用raw模块（绕过Python依赖）
            auto_fallback: 当command模块失败时，是否自动回退到raw模块
        """
        # 选择初始模块
        module = 'raw' if use_raw else 'command'
        cmd = ['ansible', hosts, '-m', module, '-a', command]
        if self.hosts_path:
            cmd.extend(['-i', self.hosts_path])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 如果使用command模块失败，且启用了自动回退，尝试使用raw模块
        if not use_raw and auto_fallback and result.returncode != 0:
            # 检查错误是否与Python兼容性有关
            python_compat_errors = ['SyntaxError', 'future feature annotations is not defined', 'No start of json char found']
            if any(error in result.stdout or error in result.stderr for error in python_compat_errors):
                print(f"Command module failed with Python compatibility error, falling back to raw module for command: {command}")
                # 使用raw模块重试
                raw_cmd = ['ansible', hosts, '-m', 'raw', '-a', command]
                if self.hosts_path:
                    raw_cmd.extend(['-i', self.hosts_path])
                result = subprocess.run(raw_cmd, capture_output=True, text=True)
        
        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    
    def copy_file(self, hosts, src, dest):
        """复制文件"""
        cmd = ['ansible', hosts, '-m', 'copy', '-a', f'src={src} dest={dest}']
        if self.hosts_path:
            cmd.extend(['-i', self.hosts_path])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    
    def template(self, hosts, src, dest, vars=None):
        """模板部署"""
        cmd = ['ansible', hosts, '-m', 'template', '-a', f'src={src} dest={dest}']
        if vars:
            cmd.extend(['-e', json.dumps(vars)])
        if self.hosts_path:
            cmd.extend(['-i', self.hosts_path])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    
    def playbook(self, playbook_path, extra_vars=None):
        """执行Playbook"""
        cmd = ['ansible-playbook', playbook_path]
        if extra_vars:
            cmd.extend(['-e', json.dumps(extra_vars)])
        if self.hosts_path:
            cmd.extend(['-i', self.hosts_path])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    
    def get_server_info(self, ip, port=22, username=None, password=None):
        """使用ansible获取服务器信息
        
        优化说明：
        - 根据目标IP类型自动选择SSH参数
        - 私网到公网场景增强连接稳定性
        """
        def _get_ssh_args():
            if self.deployment_mode == 'private_to_public' or (self.deployment_mode == 'auto' and not self._is_private_ip(ip)):
                return self.SSH_COMMON_ARGS_PRIVATE_TO_PUBLIC
            return self.SSH_COMMON_ARGS_DEFAULT
        
        if self.hosts_path:
            try:
                os_result = self.run_command(ip, 'cat /etc/os-release | grep PRETTY_NAME | cut -d"=" -f2 | tr -d "\""')
                cpu_result = self.run_command(ip, 'nproc')
                mem_result = self.run_command(ip, 'free -m | grep Mem | awk "{print $2}"')
                disk_result = self.run_command(ip, 'df -BG / | grep / | awk "{print $2}" | sed "s/G//"')
                
                os_info = None
                if os_result['returncode'] == 0:
                    os_info = os_result['stdout'].strip()
                
                cpu = None
                if cpu_result['returncode'] == 0:
                    cpu_match = re.search(r'\d+', cpu_result['stdout'])
                    if cpu_match:
                        cpu = int(cpu_match.group(0))
                
                memory = None
                if mem_result['returncode'] == 0:
                    mem_match = re.search(r'\d+', mem_result['stdout'])
                    if mem_match:
                        memory = round(int(mem_match.group(0)) / 1024, 1)
                
                disk = None
                if disk_result['returncode'] == 0:
                    disk_match = re.search(r'\d+', disk_result['stdout'])
                    if disk_match:
                        disk = int(disk_match.group(0))
                
                return {
                    'os': os_info,
                    'cpu': cpu,
                    'memory': memory,
                    'disk': disk
                }
            except Exception as e:
                print(f"获取服务器信息失败: {e}")
                return None
        else:
            ssh_args = _get_ssh_args()
            
            if self.ssh_key_path and os.path.exists(self.ssh_key_path):
                temp_host = f'[{ip}]\n{ip} ansible_port={port} ansible_user={username} ansible_ssh_private_key_file={self.ssh_key_path} ansible_ssh_common_args="{ssh_args}"'
            elif password:
                temp_host = f'[{ip}]\n{ip} ansible_port={port} ansible_user={username} ansible_password={password} ansible_ssh_common_args="{ssh_args}"'
            else:
                temp_host = f'[{ip}]\n{ip} ansible_port={port} ansible_user={username} ansible_ssh_common_args="{ssh_args}"'
            
            temp_dir = tempfile.gettempdir()
            temp_hosts_path = os.path.join(temp_dir, f'ansible_temp_hosts_{ip}')
            
            with open(temp_hosts_path, 'w') as f:
                f.write(temp_host)
            
            try:
                original_hosts_path = self.hosts_path
                self.hosts_path = temp_hosts_path
                
                os_result = self.run_command(ip, 'cat /etc/os-release | grep PRETTY_NAME | cut -d"=" -f2 | tr -d "\""')
                cpu_result = self.run_command(ip, 'nproc')
                mem_result = self.run_command(ip, 'free -m | grep Mem | awk "{print $2}"')
                disk_result = self.run_command(ip, 'df -BG / | grep / | awk "{print $2}" | sed "s/G//"')
                
                os_info = None
                if os_result['returncode'] == 0:
                    os_info = os_result['stdout'].strip()
                
                cpu = None
                if cpu_result['returncode'] == 0:
                    cpu_match = re.search(r'\d+', cpu_result['stdout'])
                    if cpu_match:
                        cpu = int(cpu_match.group(0))
                
                memory = None
                if mem_result['returncode'] == 0:
                    mem_match = re.search(r'\d+', mem_result['stdout'])
                    if mem_match:
                        memory = round(int(mem_match.group(0)) / 1024, 1)
                
                disk = None
                if disk_result['returncode'] == 0:
                    disk_match = re.search(r'\d+', disk_result['stdout'])
                    if disk_match:
                        disk = int(disk_match.group(0))
                
                return {
                    'os': os_info,
                    'cpu': cpu,
                    'memory': memory,
                    'disk': disk
                }
            except Exception as e:
                print(f"获取服务器信息失败: {e}")
                return None
            finally:
                self.hosts_path = original_hosts_path
                if os.path.exists(temp_hosts_path):
                    os.remove(temp_hosts_path)
    
    def ping_server(self, ip, port=22, username=None, password=None):
        """使用ansible ping服务器
        
        优化说明：
        - 根据部署模式选择SSH连接参数
        - 增强私网到公网场景的连接稳定性
        """
        def _get_ssh_args():
            if self.deployment_mode == 'private_to_public' or (self.deployment_mode == 'auto' and not self._is_private_ip(ip)):
                return self.SSH_COMMON_ARGS_PRIVATE_TO_PUBLIC
            return self.SSH_COMMON_ARGS_DEFAULT
        
        def _execute_ping(hosts_path, use_raw=False):
            try:
                if use_raw:
                    cmd = ['ansible', ip, '-m', 'raw', '-a', 'echo pong', '-i', hosts_path]
                else:
                    cmd = ['ansible', ip, '-m', 'ping', '-i', hosts_path]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if use_raw:
                    return result.returncode == 0 and 'pong' in result.stdout.lower()
                return result.returncode == 0
            except Exception as e:
                print(f"Ping服务器失败: {e}")
                return False
        
        if self.hosts_path:
            if _execute_ping(self.hosts_path):
                return True
            else:
                print(f"Ping模块失败，尝试使用raw模块ping服务器: {ip}")
                return _execute_ping(self.hosts_path, use_raw=True)
        else:
            ssh_args = _get_ssh_args()
            
            if self.ssh_key_path and os.path.exists(self.ssh_key_path):
                temp_host = f'''[{ip}]
{ip} ansible_port={port} ansible_user={username} ansible_ssh_private_key_file={self.ssh_key_path} ansible_ssh_common_args="{ssh_args}"'''
            elif password:
                temp_host = f'''[{ip}]
{ip} ansible_port={port} ansible_user={username} ansible_password={password} ansible_ssh_common_args="{ssh_args}"'''
            else:
                temp_host = f'''[{ip}]
{ip} ansible_port={port} ansible_user={username} ansible_ssh_common_args="{ssh_args}"'''
            
            temp_dir = tempfile.gettempdir()
            temp_hosts_path = os.path.join(temp_dir, f'ansible_temp_hosts_{ip}')
            
            with open(temp_hosts_path, 'w') as f:
                f.write(temp_host)
            
            try:
                if _execute_ping(temp_hosts_path):
                    return True
                else:
                    print(f"Ping模块失败，尝试使用raw模块ping服务器: {ip}")
                    return _execute_ping(temp_hosts_path, use_raw=True)
            except Exception as e:
                print(f"Ping服务器失败: {e}")
                return False
            finally:
                if os.path.exists(temp_hosts_path):
                    os.remove(temp_hosts_path)