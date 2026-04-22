import paramiko
import time
import os
import socket
import logging
from typing import Optional, List, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_ssh_key(key_path: str, password: str = None) -> Optional[paramiko.PKey]:
    """加载SSH密钥文件"""
    try:
        if password:
            return paramiko.RSAKey.from_private_key_file(key_path, password=password)
        return paramiko.RSAKey.from_private_key_file(key_path)
    except Exception as e:
        logger.error(f"加载密钥失败: {e}")
        return None


class SSHClient:
    """SSH客户端封装 - 优化版"""
    
    def __init__(self, hostname, port=22, username=None, password=None, key_path=None):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        self.client = None
        self._connection_method = None
    
    def _get_connection_method(self) -> str:
        """确定连接方式优先级"""
        if self.key_path and os.path.exists(self.key_path):
            return 'key'
        elif self.password:
            return 'password'
        return 'none'
    
    def connect(self, timeout=10) -> bool:
        """建立SSH连接 - 优化版"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connection_method = self._get_connection_method()
            self._connection_method = connection_method
            
            if connection_method == 'key':
                return self._connect_with_key(timeout)
            elif connection_method == 'password':
                return self._connect_with_password(timeout)
            else:
                logger.error("没有可用的认证方式")
                return False
                
        except Exception as e:
            logger.debug(f"SSH连接失败: {e}")
            return False
    
    def _connect_with_key(self, timeout: int) -> bool:
        """使用密钥文件连接"""
        try:
            key = load_ssh_key(self.key_path)
            if key:
                self.client.connect(
                    hostname=self.hostname,
                    port=self.port,
                    username=self.username,
                    pkey=key,
                    timeout=timeout
                )
                logger.debug(f"使用密钥连接到 {self.hostname} 成功")
                return True
            return False
        except Exception as e:
            logger.debug(f"密钥连接失败: {e}")
            return False
    
    def _connect_with_password(self, timeout: int) -> bool:
        """使用密码连接"""
        try:
            self.client.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=timeout
            )
            logger.debug(f"使用密码连接到 {self.hostname} 成功")
            return True
        except Exception as e:
            logger.debug(f"密码连接失败: {e}")
            return False
    
    def execute_command(self, command, timeout=30):
        """执行SSH命令"""
        if not self.client:
            if not self.connect():
                return None
        
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            return {
                'output': output,
                'error': error,
                'exit_code': stdout.channel.recv_exit_status()
            }
        except Exception as e:
            logger.debug(f"命令执行失败: {e}")
            return None
    
    def close(self):
        """关闭SSH连接"""
        if self.client:
            self.client.close()
    
    def __enter__(self):
        """上下文管理器进入"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.close()
    
    def get_server_info(self):
        """获取服务器信息"""
        os_release = self.execute_command('cat /etc/os-release')
        cpu_info = self.execute_command('nproc')
        free_info = self.execute_command('free -m')
        df_info = self.execute_command('df -BG /')
        
        os_value = None
        if os_release:
            for line in os_release['output'].split('\n'):
                if line.startswith('PRETTY_NAME='):
                    os_value = line.split('=')[1].strip().strip('"')
                    break
        
        cpu_value = None
        if cpu_info:
            try:
                cpu_value = int(cpu_info['output'].strip())
            except ValueError:
                pass
        
        memory_value = None
        if free_info:
            for line in free_info['output'].split('\n'):
                if line.startswith('Mem:'):
                    try:
                        parts = line.split()
                        if len(parts) >= 2:
                            total_mem_mb = int(parts[1])
                            if total_mem_mb <= 512:
                                memory_value = round(total_mem_mb / 1024, 3)
                            else:
                                memory_value = round(total_mem_mb / 1024, 3)
                        break
                    except (ValueError, IndexError):
                        pass
        
        disk_value = None
        if df_info:
            for line in df_info['output'].split('\n'):
                if '/dev/' in line or '文件系统' not in line:
                    try:
                        parts = line.split()
                        if len(parts) >= 2:
                            disk_size = parts[1]
                            if disk_size.endswith('G'):
                                disk_value = int(disk_size[:-1])
                            else:
                                disk_value = int(disk_size)
                        break
                    except (ValueError, IndexError):
                        pass
        
        return {
            'os': os_value,
            'cpu': cpu_value,
            'memory': memory_value,
            'disk': disk_value
        }
