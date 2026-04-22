"""
Server Auto-Configuration Manager

This module provides automatic detection and configuration of new servers
added to the cloud management system. It integrates with the existing
SSHConfigManager and AnsibleAPI to provide a complete automation solution.

Features:
- Automatic detection of newly added servers
- Integration with database server records
- Bulk configuration capabilities
- Configuration status tracking
- Webhook notifications for configuration events

Author: Cloud Management Platform
Version: 1.0.0
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.ssh_config_manager import SSHConfigManager, ServerConfig, create_server_config
from app.utils.ansible_api import AnsibleAPI


class ServerStatus(Enum):
    """Status of server in the management system"""
    PENDING = "pending"
    CONFIGURED = "configured"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class NewServerDetector:
    """
    Detects newly added servers from various sources.
    
    Sources:
    - Database server table
    - Configuration files
    - API endpoints
    - Manual additions
    """
    
    def __init__(self, db_session=None, config_file: Optional[str] = None):
        """
        Initialize the detector.
        
        Args:
            db_session: Database session for querying server records
            config_file: Path to server list configuration file
        """
        self.db_session = db_session
        self.config_file = config_file
        self.logger = logging.getLogger('NewServerDetector')
        self._known_servers = set()
        self._load_known_servers()
    
    def _load_known_servers(self):
        """Load known server list from storage"""
        if self.config_file and os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self._known_servers = set(data.get('known_servers', []))
            except Exception as e:
                self.logger.warning(f"Could not load known servers: {e}")
    
    def _save_known_servers(self):
        """Save known server list to storage"""
        if self.config_file:
            try:
                os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
                with open(self.config_file, 'w') as f:
                    json.dump({
                        'known_servers': list(self._known_servers),
                        'last_updated': datetime.now().isoformat()
                    }, f, indent=2)
            except Exception as e:
                self.logger.error(f"Could not save known servers: {e}")
    
    def detect_from_database(self, server_model) -> List[ServerConfig]:
        """
        Detect new servers from database.
        
        Args:
            server_model: SQLAlchemy model for servers table
            
        Returns:
            List of new ServerConfig objects
        """
        new_servers = []
        
        try:
            if self.db_session:
                all_servers = self.db_session.query(server_model).all()
                
                for server in all_servers:
                    server_key = f"{server.ip}:{server.port}"
                    
                    if server_key not in self._known_servers:
                        self.logger.info(f"New server detected: {server.ip}")
                        
                        server_config = create_server_config(
                            ip=server.ip,
                            port=server.port,
                            username=server.username,
                            password=server.password,
                            ssh_key_path=server.ssh_key_path
                        )
                        
                        new_servers.append(server_config)
                        self._known_servers.add(server_key)
        except Exception as e:
            self.logger.error(f"Database detection failed: {e}")
        
        return new_servers
    
    def detect_from_file(self, server_list_file: str) -> List[ServerConfig]:
        """
        Detect new servers from a file list.
        
        Args:
            server_list_file: Path to file containing server list
            
        Returns:
            List of new ServerConfig objects
        """
        new_servers = []
        
        try:
            if os.path.exists(server_list_file):
                with open(server_list_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            parts = line.split(',')
                            
                            if len(parts) >= 1:
                                ip = parts[0].strip()
                                port = int(parts[1].strip()) if len(parts) > 1 else 22
                                username = parts[2].strip() if len(parts) > 2 else 'root'
                                
                                server_key = f"{ip}:{port}"
                                
                                if server_key not in self._known_servers:
                                    self.logger.info(f"New server from file: {ip}")
                                    
                                    server_config = create_server_config(
                                        ip=ip,
                                        port=port,
                                        username=username
                                    )
                                    
                                    new_servers.append(server_config)
                                    self._known_servers.add(server_key)
        except Exception as e:
            self.logger.error(f"File detection failed: {e}")
        
        return new_servers
    
    def detect_all(self, server_model=None, server_list_file: Optional[str] = None) -> List[ServerConfig]:
        """
        Detect new servers from all sources.
        
        Args:
            server_model: Database model for servers
            server_list_file: Optional file with server list
            
        Returns:
            List of all new ServerConfig objects
        """
        all_new_servers = []
        
        # Detect from database
        if server_model:
            db_servers = self.detect_from_database(server_model)
            all_new_servers.extend(db_servers)
        
        # Detect from file
        if server_list_file:
            file_servers = self.detect_from_file(server_list_file)
            all_new_servers.extend(file_servers)
        
        # Save updated known servers
        self._save_known_servers()
        
        return all_new_servers
    
    def mark_as_configured(self, server_config: ServerConfig):
        """Mark a server as configured"""
        server_key = f"{server_config.ip}:{server_config.port}"
        self._known_servers.add(server_key)
        self._save_known_servers()
    
    def mark_as_failed(self, server_config: ServerConfig):
        """Mark a server as failed (but still known)"""
        server_key = f"{server_config.ip}:{server_config.port}"
        self._known_servers.add(server_key)
        self._save_known_servers()


class AutoConfigurationManager:
    """
    Manages automatic configuration of new servers.
    
    Features:
    - Automatic detection of new servers
    - PubkeyAuthentication configuration
    - SSH key deployment
    - Configuration validation
    - Audit logging
    - Status tracking
    """
    
    def __init__(self, 
                 ssh_key_path: Optional[str] = None,
                 db_session=None,
                 config_file: Optional[str] = None,
                 notification_callback=None):
        """
        Initialize the auto-configuration manager.
        
        Args:
            ssh_key_path: Path to SSH private key
            db_session: Database session
            config_file: File to store known servers
            notification_callback: Optional callback for notifications
        """
        self.ssh_config_manager = SSHConfigManager(ssh_key_path=ssh_key_path)
        self.detector = NewServerDetector(db_session, config_file)
        self.notification_callback = notification_callback
        self.logger = logging.getLogger('AutoConfigurationManager')
        
        # Track configuration status
        self._config_status: Dict[str, Dict[str, Any]] = {}
        
    def configure_new_servers(self, 
                             servers: List[ServerConfig],
                             enable_pubkey: bool = True,
                             deploy_ssh_key: bool = True) -> Dict:
        """
        Configure a list of new servers.
        
        Args:
            servers: List of servers to configure
            enable_pubkey: Whether to enable PubkeyAuthentication
            deploy_ssh_key: Whether to deploy SSH public key
            
        Returns:
            Configuration results summary
        """
        self.logger.info(f"Starting auto-configuration for {len(servers)} servers")
        
        results = {
            'total': len(servers),
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'timestamp': datetime.now().isoformat(),
            'details': []
        }
        
        for server in servers:
            server_result = self._configure_single_server(
                server, 
                enable_pubkey, 
                deploy_ssh_key
            )
            
            results['details'].append(server_result)
            
            if server_result['success']:
                results['successful'] += 1
                self.detector.mark_as_configured(server)
            elif server_result.get('skipped'):
                results['skipped'] += 1
            else:
                results['failed'] += 1
                self.detector.mark_as_failed(server)
            
            # Store status
            self._config_status[server.ip] = server_result
        
        # Send notification if callback configured
        if self.notification_callback:
            self.notification_callback(results)
        
        self.logger.info(
            f"Auto-configuration completed: {results['successful']} success, "
            f"{results['failed']} failed, {results['skipped']} skipped"
        )
        
        return results
    
    def _configure_single_server(self,
                                server: ServerConfig,
                                enable_pubkey: bool,
                                deploy_ssh_key: bool) -> Dict:
        """
        Configure a single server.
        
        Args:
            server: Server configuration
            enable_pubkey: Whether to enable PubkeyAuthentication
            deploy_ssh_key: Whether to deploy SSH public key
            
        Returns:
            Configuration result dictionary
        """
        result = {
            'ip': server.ip,
            'port': server.port,
            'username': server.username,
            'success': False,
            'steps': [],
            'error': None
        }
        
        try:
            # Step 1: Check SSH connectivity
            self.logger.info(f"Checking connectivity to {server.ip}")
            connectivity_result = self._check_connectivity(server)
            result['steps'].append({
                'step': 'connectivity_check',
                'success': connectivity_result,
                'message': 'Server is reachable' if connectivity_result else 'Server is not reachable'
            })
            
            if not connectivity_result:
                result['error'] = 'Server is not reachable'
                return result
            
            # Step 2: Enable PubkeyAuthentication
            if enable_pubkey:
                self.logger.info(f"Enabling PubkeyAuthentication on {server.ip}")
                config_result = self.ssh_config_manager.configure_server(
                    server, 
                    enable_pubkey=True, 
                    validate=True
                )
                
                result['steps'].append({
                    'step': 'pubkey_configuration',
                    'success': config_result['success'],
                    'details': config_result
                })
                
                if not config_result['success']:
                    result['error'] = config_result.get('error', 'Configuration failed')
                    return result
            
            # Step 3: Deploy SSH public key
            if deploy_ssh_key and self.ssh_config_manager.ssh_key_path:
                self.logger.info(f"Deploying SSH key to {server.ip}")
                deploy_result = self._deploy_ssh_key(server)
                
                result['steps'].append({
                    'step': 'ssh_key_deployment',
                    'success': deploy_result,
                    'message': 'SSH key deployed' if deploy_result else 'SSH key deployment failed'
                })
                
                if not deploy_result:
                    result['error'] = 'SSH key deployment failed'
                    return result
            
            # Step 4: Verify configuration
            self.logger.info(f"Verifying configuration on {server.ip}")
            verify_result = self._verify_configuration(server)
            
            result['steps'].append({
                'step': 'configuration_verification',
                'success': verify_result,
                'message': 'Configuration verified' if verify_result else 'Configuration verification failed'
            })
            
            if not verify_result:
                result['error'] = 'Configuration verification failed'
                return result
            
            result['success'] = True
            self.logger.info(f"Server {server.ip} configured successfully")
            
        except Exception as e:
            result['error'] = str(e)
            self.logger.error(f"Configuration failed for {server.ip}: {e}")
        
        return result
    
    def _check_connectivity(self, server: ServerConfig) -> bool:
        """Check if server is reachable via SSH"""
        try:
            cmd = [
                'ssh',
                '-o', 'ConnectTimeout=10',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-p', str(server.port),
                f'{server.username}@{server.ip}',
                'echo connectivity_ok'
            ]
            
            if self.ssh_config_manager.ssh_key_path:
                cmd.insert(1, '-i')
                cmd.insert(2, self.ssh_config_manager.ssh_key_path)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return 'connectivity_ok' in result.stdout
            
        except Exception:
            return False
    
    def _deploy_ssh_key(self, server: ServerConfig) -> bool:
        """Deploy SSH public key to server"""
        try:
            pubkey_file = self.ssh_config_manager.ssh_key_path + '.pub'
            
            if not os.path.exists(pubkey_file):
                self.logger.warning(f"Public key not found: {pubkey_file}")
                return False
            
            with open(pubkey_file, 'r') as f:
                public_key = f.read().strip()
            
            # Create .ssh directory and authorized_keys
            commands = [
                f'mkdir -p ~/.ssh && chmod 700 ~/.ssh',
                f'echo "{public_key}" >> ~/.ssh/authorized_keys',
                f'chmod 600 ~/.ssh/authorized_keys'
            ]
            
            for cmd in commands:
                full_cmd = [
                    'ssh',
                    '-o', 'StrictHostKeyChecking=no',
                    '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=30',
                    '-p', str(server.port),
                ]
                
                if self.ssh_config_manager.ssh_key_path:
                    full_cmd.extend(['-i', self.ssh_config_manager.ssh_key_path])
                
                full_cmd.extend([
                    f'{server.username}@{server.ip}',
                    cmd
                ])
                
                result = subprocess.run(
                    full_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode != 0:
                    self.logger.error(f"Key deployment command failed: {cmd}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Key deployment failed: {e}")
            return False
    
    def _verify_configuration(self, server: ServerConfig) -> bool:
        """Verify SSH configuration on server"""
        try:
            # Test public key authentication
            test_cmd = [
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=30',
                '-o', 'PreferredAuthentications=publickey',
                '-p', str(server.port),
            ]
            
            if self.ssh_config_manager.ssh_key_path:
                test_cmd.extend(['-i', self.ssh_config_manager.ssh_key_path])
            
            test_cmd.extend([
                f'{server.username}@{server.ip}',
                'echo verification_ok && exit 0'
            ])
            
            result = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return 'verification_ok' in result.stdout
            
        except Exception:
            return False
    
    def get_configuration_status(self, ip: Optional[str] = None) -> Dict:
        """
        Get configuration status for servers.
        
        Args:
            ip: Optional server IP to filter results
            
        Returns:
            Configuration status dictionary
        """
        if ip:
            return self._config_status.get(ip, {'status': 'unknown'})
        
        return {
            'total_servers': len(self._config_status),
            'successful': sum(1 for s in self._config_status.values() if s.get('success')),
            'failed': sum(1 for s in self._config_status.values() if not s.get('success') and s.get('error')),
            'servers': self._config_status
        }


class ConfigurationScheduler:
    """
    Scheduler for periodic configuration checks and updates.
    
    Features:
    - Scheduled detection of new servers
    - Periodic configuration validation
    - Background thread execution
    - Configurable intervals
    """
    
    def __init__(self, 
                 auto_config_manager: AutoConfigurationManager,
                 check_interval: int = 300):
        """
        Initialize the scheduler.
        
        Args:
            auto_config_manager: Manager to use for configuration
            check_interval: Interval in seconds between checks
        """
        self.manager = auto_config_manager
        self.check_interval = check_interval
        self.logger = logging.getLogger('ConfigurationScheduler')
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
    def start(self):
        """Start the scheduler in a background thread"""
        if self._running:
            self.logger.warning("Scheduler is already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"Scheduler started with {self.check_interval}s interval")
    
    def stop(self):
        """Stop the scheduler"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self.logger.info("Scheduler stopped")
    
    def _run_loop(self):
        """Main scheduler loop"""
        while self._running:
            try:
                # Detect and configure new servers
                new_servers = self.manager.detector.detect_all()
                
                if new_servers:
                    self.logger.info(f"Found {len(new_servers)} new servers")
                    self.manager.configure_new_servers(new_servers)
                
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
            
            # Wait for next interval
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)


# Flask Blueprint Integration
def create_auto_config_blueprint(db_session, config_dir: str = '/code/cloud-management-platform'):
    """
    Create a Flask blueprint for auto-configuration API endpoints.
    
    Args:
        db_session: Database session factory
        config_dir: Directory for configuration files
        
    Returns:
        Flask Blueprint with auto-configuration routes
    """
    try:
        from flask import Blueprint, request, jsonify
        
        blueprint = Blueprint('auto_config', __name__)
        
        # Get server model from db_session
        Server = db_session().query_servers_table() if hasattr(db_session, 'query_servers_table') else None
        
        # Initialize managers
        config_file = os.path.join(config_dir, 'data', 'known_servers.json')
        auto_config_manager = AutoConfigurationManager(
            ssh_key_path=None,
            db_session=db_session,
            config_file=config_file
        )
        
        @blueprint.route('/api/auto-config/detect', methods=['POST'])
        def detect_servers():
            """Detect and return new servers"""
            new_servers = auto_config_manager.detector.detect_all(Server)
            
            return jsonify({
                'success': True,
                'new_servers': [
                    {
                        'ip': s.ip,
                        'port': s.port,
                        'username': s.username
                    }
                    for s in new_servers
                ]
            })
        
        @blueprint.route('/api/auto-config/configure', methods=['POST'])
        def configure_servers():
            """Configure new servers"""
            data = request.json or {}
            enable_pubkey = data.get('enable_pubkey', True)
            deploy_key = data.get('deploy_ssh_key', True)
            
            new_servers = auto_config_manager.detector.detect_all(Server)
            
            if not new_servers:
                return jsonify({
                    'success': True,
                    'message': 'No new servers detected',
                    'results': {'total': 0, 'successful': 0, 'failed': 0}
                })
            
            results = auto_config_manager.configure_new_servers(
                new_servers,
                enable_pubkey=enable_pubkey,
                deploy_ssh_key=deploy_key
            )
            
            return jsonify({
                'success': results['successful'] > 0 or results['total'] == 0,
                'message': f"Configured {results['successful']}/{results['total']} servers",
                'results': results
            })
        
        @blueprint.route('/api/auto-config/status', methods=['GET'])
        def get_status():
            """Get configuration status"""
            status = auto_config_manager.get_configuration_status()
            return jsonify({
                'success': True,
                'status': status
            })
        
        @blueprint.route('/api/auto-config/configure-single', methods=['POST'])
        def configure_single():
            """Configure a single server"""
            data = request.json
            
            if not data or 'ip' not in data:
                return jsonify({
                    'success': False,
                    'error': 'Server IP is required'
                }), 400
            
            server = create_server_config(
                ip=data['ip'],
                port=data.get('port', 22),
                username=data.get('username', 'root'),
                password=data.get('password'),
                ssh_key_path=data.get('ssh_key_path')
            )
            
            result = auto_config_manager._configure_single_server(
                server,
                enable_pubkey=data.get('enable_pubkey', True),
                deploy_ssh_key=data.get('deploy_ssh_key', True)
            )
            
            return jsonify({
                'success': result['success'],
                'result': result
            })
        
        return blueprint
        
    except ImportError:
        # Flask not available, return None
        return None


if __name__ == '__main__':
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description='Server Auto-Configuration Manager')
    parser.add_argument('--detect', action='store_true', help='Detect new servers')
    parser.add_argument('--configure', action='store_true', help='Configure new servers')
    parser.add_argument('--server', help='Configure single server IP')
    parser.add_argument('--status', action='store_true', help='Show configuration status')
    parser.add_argument('--key', help='Path to SSH private key')
    parser.add_argument('--enable-pubkey', action='store_true', help='Enable PubkeyAuthentication')
    parser.add_argument('--deploy-key', action='store_true', help='Deploy SSH key')
    
    args = parser.parse_args()
    
    # Initialize manager
    manager = AutoConfigurationManager(ssh_key_path=args.key)
    
    if args.detect:
        servers = manager.detector.detect_all()
        print(f"Detected {len(servers)} new servers:")
        for s in servers:
            print(f"  - {s.ip}:{s.port} ({s.username})")
    
    if args.configure:
        servers = manager.detector.detect_all()
        if servers:
            results = manager.configure_new_servers(
                servers,
                enable_pubkey=args.enable_pubkey,
                deploy_ssh_key=args.deploy_key
            )
            print(json.dumps(results, indent=2))
    
    if args.server:
        server = create_server_config(
            ip=args.server,
            port=22,
            username='root'
        )
        result = manager._configure_single_server(
            server,
            enable_pubkey=args.enable_pubkey,
            deploy_ssh_key=args.deploy_key
        )
        print(json.dumps(result, indent=2))
    
    if args.status:
        print(json.dumps(manager.get_configuration_status(), indent=2))
