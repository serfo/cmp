#!/usr/bin/env python3
"""
SSH Pubkey Authentication Configuration Manager

This module provides automated detection, configuration, validation,
and logging for SSH PubkeyAuthentication settings on servers.

Author: Cloud Management Platform
Version: 1.0.0
"""

import os
import re
import subprocess
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum


class ConfigurationStatus(Enum):
    """Status of configuration operation"""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class ServerConfig:
    """Server configuration details"""
    ip: str
    port: int
    username: str
    password: Optional[str] = None
    ssh_key_path: Optional[str] = None
    current_pubkey_setting: Optional[str] = None
    desired_pubkey_setting: str = "yes"


@dataclass
class ConfigChange:
    """Record of configuration change"""
    timestamp: str
    server_ip: str
    operation: str
    original_value: Optional[str]
    new_value: Optional[str]
    status: str
    details: Optional[str]


class SSHConfigManager:
    """
    Manages SSH configuration for servers, with focus on PubkeyAuthentication.
    
    Features:
    - Automated detection of configuration status
    - Safe configuration modifications with backup
    - Validation and rollback capabilities
    - Comprehensive audit logging
    """
    
    # SSH configuration directives to check/modify
    SSH_CONFIG_DIRECTIVES = [
        'PubkeyAuthentication',
        'PasswordAuthentication',
        'PermitRootLogin',
        'StrictModes',
        'AuthorizedKeysFile',
        'PasswordAuthentication'
    ]
    
    # Desired secure configuration
    SECURE_SSH_CONFIG = {
        'PubkeyAuthentication': 'yes',
        'PasswordAuthentication': 'no',  # Optional: disable password auth
        'PermitRootLogin': 'prohibit-password',  # Root login only with key
        'StrictModes': 'yes',
        'AuthorizedKeysFile': '.ssh/authorized_keys',
    }
    
    # Audit log directory
    AUDIT_LOG_DIR = '/var/log/ssh_config_audit'
    
    def __init__(self, ssh_key_path: Optional[str] = None, 
                 log_file: Optional[str] = None):
        """
        Initialize SSH Config Manager.
        
        Args:
            ssh_key_path: Path to SSH private key for authentication
            log_file: Custom log file path (optional)
        """
        self.ssh_key_path = ssh_key_path or self._find_ssh_key()
        self.logger = self._setup_logger(log_file)
        self._ensure_audit_log_dir()
        
    def _find_ssh_key(self) -> Optional[str]:
        """Find available SSH key"""
        key_paths = [
            os.path.expanduser('~/.ssh/id_ed25519'),
            os.path.expanduser('~/.ssh/id_rsa'),
            os.path.expanduser('~/.ssh/cloud-management/id_ed25519_latest'),
        ]
        
        for path in key_paths:
            if os.path.exists(path):
                return path
        return None
    
    def _setup_logger(self, log_file: Optional[str]) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('SSHConfigManager')
        logger.setLevel(logging.INFO)
        
        # Avoid duplicate handlers
        if logger.handlers:
            return logger
            
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler
        log_path = log_file or os.path.join(
            self.AUDIT_LOG_DIR, 
            f'ssh_config_{datetime.now().strftime("%Y%m%d")}.log'
        )
        file_handler = logging.FileHandler(log_path, mode='a')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        return logger
    
    def _ensure_audit_log_dir(self):
        """Ensure audit log directory exists"""
        try:
            Path(self.AUDIT_LOG_DIR).mkdir(parents=True, exist_ok=True)
            audit_log = Path(self.AUDIT_LOG_DIR)
            audit_log.chmod(0o755)
        except Exception as e:
            self.logger.warning(f"Could not create audit log directory: {e}")
    
    def _execute_ssh_command(self, server: ServerConfig, 
                           command: str) -> Tuple[bool, str, str]:
        """
        Execute command on remote server via SSH.
        
        Args:
            server: Server configuration
            command: Command to execute
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        try:
            # Build SSH command
            ssh_cmd = [
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=30',
                '-p', str(server.port),
            ]
            
            if self.ssh_key_path and os.path.exists(self.ssh_key_path):
                ssh_cmd.extend(['-i', self.ssh_key_path])
            elif server.password:
                ssh_cmd.extend([
                    '-o', f'PasswordAuthentication=yes',
                    '-o', 'PreferredAuthentications=password',
                ])
            
            ssh_cmd.extend([
                f'{server.username}@{server.ip}',
                command
            ])
            
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            return result.returncode == 0, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def check_current_config(self, server: ServerConfig) -> Dict[str, str]:
        """
        Check current SSH configuration on server.
        
        Args:
            server: Server configuration
            
        Returns:
            Dictionary of current configuration settings
        """
        self.logger.info(f"Checking SSH configuration on {server.ip}")
        
        config = {}
        
        for directive in self.SSH_CONFIG_DIRECTIVES:
            cmd = f"grep -E '^{directive}' /etc/ssh/sshd_config 2>/dev/null | head -1 || echo 'NOT_FOUND'"
            success, stdout, stderr = self._execute_ssh_command(server, cmd)
            
            if success and stdout.strip() != 'NOT_FOUND':
                # Parse the configuration line
                match = re.match(rf'^{directive}\s+(\w+)', stdout.strip())
                if match:
                    config[directive] = match.group(1)
                else:
                    config[directive] = stdout.strip().split()[-1] if stdout.strip() else 'not set'
            else:
                config[directive] = 'not set'
        
        server.current_pubkey_setting = config.get('PubkeyAuthentication', 'not set')
        self.logger.info(f"Current PubkeyAuthentication on {server.ip}: {server.current_pubkey_setting}")
        
        return config
    
    def backup_config(self, server: ServerConfig) -> bool:
        """
        Create backup of current SSH configuration.
        
        Args:
            server: Server configuration
            
        Returns:
            True if backup successful
        """
        self.logger.info(f"Creating backup of SSH config on {server.ip}")
        
        backup_cmd = f"cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup.$(date +%Y%m%d%H%M%S)"
        success, stdout, stderr = self._execute_ssh_command(server, backup_cmd)
        
        if success:
            self.logger.info(f"Backup created successfully on {server.ip}")
            return True
        else:
            self.logger.error(f"Failed to create backup on {server.ip}: {stderr}")
            return False
    
    def modify_pubkey_config(self, server: ServerConfig,
                           enable: bool = True,
                           backup: bool = True) -> ConfigChange:
        """
        Modify PubkeyAuthentication configuration on server.
        
        Args:
            server: Server configuration
            enable: Whether to enable PubkeyAuthentication
            backup: Whether to create backup before modification
            
        Returns:
            ConfigChange record of the operation
        """
        new_value = 'yes' if enable else 'no'
        self.logger.info(f"Modifying PubkeyAuthentication on {server.ip} to '{new_value}'")
        
        # Create backup if requested
        if backup and not self.backup_config(server):
            return ConfigChange(
                timestamp=datetime.now().isoformat(),
                server_ip=server.ip,
                operation='backup',
                original_value=None,
                new_value=None,
                status='failed',
                details='Backup creation failed'
            )
        
        # Check if already in desired state
        if server.current_pubkey_setting == new_value:
            self.logger.info(f"PubkeyAuthentication already set to '{new_value}' on {server.ip}")
            return ConfigChange(
                timestamp=datetime.now().isoformat(),
                server_ip=server.ip,
                operation='modify',
                original_value=server.current_pubkey_setting,
                new_value=new_value,
                status='skipped',
                details='Configuration already in desired state'
            )
        
        # Method 1: Using sed (most compatible)
        sed_cmd = (
            f"sed -i 's/^#*PubkeyAuthentication.*/PubkeyAuthentication {new_value}/' "
            f"/etc/ssh/sshd_config && "
            f"grep -q '^PubkeyAuthentication {new_value}' /etc/ssh/sshd_config && echo 'MODIFIED' || echo 'FAILED'"
        )
        
        success, stdout, stderr = self._execute_ssh_command(server, sed_cmd)
        
        if success and 'MODIFIED' in stdout:
            self.logger.info(f"Configuration modified successfully on {server.ip}")
            
            # Reload SSH service
            reload_success, reload_out, reload_err = self._execute_ssh_command(
                server, 
                "systemctl reload sshd 2>/dev/null || service sshd reload 2>/dev/null || echo 'NO_RELOAD'"
            )
            
            return ConfigChange(
                timestamp=datetime.now().isoformat(),
                server_ip=server.ip,
                operation='modify',
                original_value=server.current_pubkey_setting,
                new_value=new_value,
                status='success',
                details=f"Configuration modified. Reload: {'success' if reload_success else 'failed/not needed'}"
            )
        else:
            # Method 2: Alternative approach using echo and tee
            alt_cmd = (
                f"grep -v '^PubkeyAuthentication' /etc/ssh/sshd_config > /tmp/sshd_config_new && "
                f"echo 'PubkeyAuthentication {new_value}' >> /tmp/sshd_config_new && "
                f"mv /tmp/sshd_config_new /etc/ssh/sshd_config && "
                f"systemctl reload sshd"
            )
            
            success, stdout, stderr = self._execute_ssh_command(server, alt_cmd)
            
            if success:
                return ConfigChange(
                    timestamp=datetime.now().isoformat(),
                    server_ip=server.ip,
                    operation='modify',
                    original_value=server.current_pubkey_setting,
                    new_value=new_value,
                    status='success',
                    details="Configuration modified using alternative method"
                )
            
            self.logger.error(f"Failed to modify configuration on {server.ip}: {stderr}")
            return ConfigChange(
                timestamp=datetime.now().isoformat(),
                server_ip=server.ip,
                operation='modify',
                original_value=server.current_pubkey_setting,
                new_value=new_value,
                status='failed',
                details=f"Error: {stderr}"
            )
    
    def validate_config(self, server: ServerConfig) -> Tuple[bool, str]:
        """
        Validate SSH configuration after modification.
        
        Args:
            server: Server configuration
            
        Returns:
            Tuple of (is_valid, message)
        """
        self.logger.info(f"Validating configuration on {server.ip}")
        
        # Check configuration syntax
        test_cmd = "sshd -t 2>&1 || echo 'VALIDATION_ERROR'"
        success, stdout, stderr = self._execute_ssh_command(server, test_cmd)
        
        if 'VALIDATION_ERROR' in stderr or (stdout and 'error' in stdout.lower()):
            return False, f"Configuration syntax error: {stdout} {stderr}"
        
        # Verify PubkeyAuthentication is enabled
        config = self.check_current_config(server)
        pubkey_status = config.get('PubkeyAuthentication', 'not set')
        
        if pubkey_status == 'yes':
            self.logger.info(f"Validation successful on {server.ip}")
            return True, f"PubkeyAuthentication is enabled ({pubkey_status})"
        else:
            return False, f"PubkeyAuthentication is not enabled ({pubkey_status})"
    
    def rollback_config(self, server: ServerConfig) -> bool:
        """
        Rollback configuration to previous backup.
        
        Args:
            server: Server configuration
            
        Returns:
            True if rollback successful
        """
        self.logger.info(f"Attempting rollback on {server.ip}")
        
        # Find latest backup
        backup_cmd = (
            "ls -t /etc/ssh/sshd_config.backup.* 2>/dev/null | head -1 | xargs -I {} "
            "cp {} /etc/ssh/sshd_config && systemctl reload sshd && echo 'ROLLBACK_SUCCESS' || echo 'ROLLBACK_FAILED'"
        )
        
        success, stdout, stderr = self._execute_ssh_command(server, backup_cmd)
        
        if success and 'ROLLBACK_SUCCESS' in stdout:
            self.logger.info(f"Rollback successful on {server.ip}")
            return True
        else:
            self.logger.error(f"Rollback failed on {server.ip}")
            return False
    
    def configure_server(self, server: ServerConfig,
                        enable_pubkey: bool = True,
                        validate: bool = True) -> Dict:
        """
        Complete server configuration workflow.
        
        Args:
            server: Server configuration
            enable_pubkey: Whether to enable PubkeyAuthentication
            validate: Whether to validate after modification
            
        Returns:
            Dictionary with configuration results
        """
        self.logger.info(f"Starting configuration workflow for {server.ip}")
        
        result = {
            'server_ip': server.ip,
            'operations': [],
            'success': False,
            'error': None
        }
        
        try:
            # Step 1: Check current configuration
            current_config = self.check_current_config(server)
            result['operations'].append({
                'step': 'check_current',
                'status': 'success',
                'config': current_config
            })
            
            # Step 2: Modify configuration
            change_record = self.modify_pubkey_config(server, enable=enable_pubkey)
            result['operations'].append({
                'step': 'modify_config',
                'status': change_record.status,
                'change': {
                    'original': change_record.original_value,
                    'new': change_record.new_value,
                    'details': change_record.details
                }
            })
            
            if change_record.status == 'failed':
                result['error'] = change_record.details
                return result
            
            # Step 3: Validate configuration
            if validate:
                is_valid, message = self.validate_config(server)
                result['operations'].append({
                    'step': 'validate',
                    'status': 'success' if is_valid else 'failed',
                    'message': message
                })
                
                if not is_valid:
                    # Attempt rollback
                    if self.rollback_config(server):
                        result['operations'].append({
                            'step': 'rollback',
                            'status': 'success',
                            'message': 'Configuration rolled back due to validation failure'
                        })
                    else:
                        result['operations'].append({
                            'step': 'rollback',
                            'status': 'failed',
                            'message': 'Validation failed and rollback also failed!'
                        })
                    result['error'] = message
                    return result
            
            result['success'] = True
            self.logger.info(f"Configuration workflow completed successfully for {server.ip}")
            
        except Exception as e:
            result['error'] = str(e)
            self.logger.error(f"Configuration workflow failed for {server.ip}: {e}")
        
        return result
    
    def configure_multiple_servers(self, servers: List[ServerConfig],
                                  enable_pubkey: bool = True) -> Dict:
        """
        Configure multiple servers.
        
        Args:
            servers: List of server configurations
            enable_pubkey: Whether to enable PubkeyAuthentication
            
        Returns:
            Dictionary with results for all servers
        """
        self.logger.info(f"Starting bulk configuration for {len(servers)} servers")
        
        results = {
            'total': len(servers),
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'results': []
        }
        
        for server in servers:
            result = self.configure_server(server, enable_pubkey)
            results['results'].append(result)
            
            if result['success']:
                results['successful'] += 1
            elif result['error'] and 'already in desired state' in str(result['error']):
                results['skipped'] += 1
            else:
                results['failed'] += 1
        
        self.logger.info(
            f"Bulk configuration completed: {results['successful']} success, "
            f"{results['failed']} failed, {results['skipped']} skipped"
        )
        
        return results
    
    def log_audit_record(self, change: ConfigChange):
        """
        Log configuration change for audit purposes.
        
        Args:
            change: Configuration change record
        """
        audit_entry = {
            'timestamp': change.timestamp,
            'server_ip': change.server_ip,
            'operation': change.operation,
            'original_value': change.original_value,
            'new_value': change.new_value,
            'status': change.status,
            'details': change.details
        }
        
        audit_file = os.path.join(
            self.AUDIT_LOG_DIR,
            'audit_log.jsonl'
        )
        
        try:
            with open(audit_file, 'a') as f:
                f.write(json.dumps(audit_entry) + '\n')
        except Exception as e:
            self.logger.warning(f"Could not write audit log: {e}")


def create_server_config(ip: str, port: int = 22,
                        username: str = 'root',
                        password: Optional[str] = None,
                        ssh_key_path: Optional[str] = None) -> ServerConfig:
    """
    Factory function to create ServerConfig instance.
    
    Args:
        ip: Server IP address
        port: SSH port
        username: SSH username
        password: SSH password (optional)
        ssh_key_path: Path to SSH private key (optional)
        
    Returns:
        ServerConfig instance
    """
    return ServerConfig(
        ip=ip,
        port=port,
        username=username,
        password=password,
        ssh_key_path=ssh_key_path
    )


if __name__ == '__main__':
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description='SSH Configuration Manager')
    parser.add_argument('--ip', required=True, help='Server IP address')
    parser.add_argument('--port', type=int, default=22, help='SSH port')
    parser.add_argument('--username', default='root', help='SSH username')
    parser.add_argument('--key', help='Path to SSH private key')
    parser.add_argument('--enable', action='store_true', help='Enable PubkeyAuthentication')
    parser.add_argument('--validate', action='store_true', help='Validate after modification')
    
    args = parser.parse_args()
    
    # Create manager
    manager = SSHConfigManager(ssh_key_path=args.key)
    
    # Create server config
    server = create_server_config(
        ip=args.ip,
        port=args.port,
        username=args.username,
        ssh_key_path=args.key
    )
    
    # Configure server
    result = manager.configure_server(server, enable_pubkey=args.enable, validate=args.validate)
    
    print(json.dumps(result, indent=2))
