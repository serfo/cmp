#!/usr/bin/env python3
"""
Zabbix API工具类
使用 pyzabbix 库实现，支持 Zabbix 7.x 的 API Token 认证
"""

import logging
from typing import List, Dict, Optional, Any
from pyzabbix import ZabbixAPI as PyZabbixAPI, ZabbixAPIException

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ZabbixAPI:
    """Zabbix API客户端
    
    基于 pyzabbix 库实现，支持 Zabbix 7.x 的 API Token 认证
    提供全面的 API 方法覆盖和错误处理
    """
    
    def __init__(self, url: str, token: str):
        # 提取基础URL，移除 api_jsonrpc.php 部分
        if '/api_jsonrpc.php' in url:
            base_url = url.replace('/api_jsonrpc.php', '')
        else:
            base_url = url.rstrip('/')
        
        self.url = url
        self.token = token
        self.zapi = None
        self.mock_mode = token == 'MOCK_MODE_TOKEN'
        
        try:
            if not self.mock_mode:
                # 初始化 pyzabbix 客户端
                self.zapi = PyZabbixAPI(base_url)
                logger.info(f"初始化Zabbix API客户端，URL: {base_url}")
            else:
                logger.info(f"初始化Zabbix API客户端，URL: {url} (模拟模式)")
                self._init_mock_data()
        except Exception as e:
            logger.error(f"初始化Zabbix API客户端失败: {str(e)}")
            self.zapi = None
    
    def _init_mock_data(self):
        """初始化模拟数据"""
        import random
        import time
        
        self.mock_hosts = [
            {
                'hostid': '10084',
                'host': 'localhost',
                'name': '本地服务器',
                'status': '0',
                'interfaces': [{'ip': '127.0.0.1', 'port': '10050', 'type': '1', 'main': '1'}]
            },
            {
                'hostid': '10085', 
                'host': '192.168.1.100',
                'name': '测试服务器',
                'status': '0',
                'interfaces': [{'ip': '192.168.1.100', 'port': '10050', 'type': '1', 'main': '1'}]
            }
        ]
        
        self.mock_problems = [
            {
                'eventid': '1',
                'name': 'CPU 使用率过高 on 本地服务器',
                'severity': '3',
                'clock': str(int(time.time()) - 3600),
                'acknowledged': '0'
            },
            {
                'eventid': '2',
                'name': '磁盘空间不足 on 测试服务器', 
                'severity': '4',
                'clock': str(int(time.time()) - 1800),
                'acknowledged': '0'
            }
        ]
    
    def _authenticate(self):
        """认证到 Zabbix API
        
        优先使用 API Token 认证（Zabbix 7.0+ 推荐），
        如果 token 无效或为空，尝试使用用户名/密码认证
        """
        if self.mock_mode:
            return True
        
        if not self.zapi:
            return False
        
        try:
            # 优先使用 token 认证（Zabbix 7.0+）
            if self.token and self.token.strip():
                logger.debug("使用 API Token 认证")
                
                # 设置 Authorization header（Zabbix 7.0+ 推荐方式）
                # 注意：apiinfo.version 必须在无 auth header 时调用
                # 所以先设置 header，再验证 token
                self.zapi.session.headers['Authorization'] = f'Bearer {self.token}'
                
                # 验证 token 是否有效（调用需要认证的方法）
                try:
                    # 尝试调用一个需要认证的方法来验证 token
                    test_result = self.zapi.user.get(output=['userid'], limit=1)
                    logger.info(f"使用 API Token 认证成功，用户数: {len(test_result)}")
                    return True
                except ZabbixAPIException as e:
                    error_msg = str(e)
                    if ("Not authorized" in error_msg or 
                        "Authentication failed" in error_msg or 
                        "Authorization" in error_msg or
                        "auth" in error_msg):
                        logger.warning("API Token 无效，尝试用户名/密码认证")
                        # 移除无效的 Authorization header
                        if 'Authorization' in self.zapi.session.headers:
                            del self.zapi.session.headers['Authorization']
                    else:
                        raise
            
            # 如果 token 无效或为空，使用用户名/密码认证
            logger.debug("使用用户名/密码认证")
            self.zapi.login('Admin', 'zabbix')
            return True
            
        except ZabbixAPIException as e:
            logger.error(f"Zabbix 认证失败: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"认证异常: {str(e)}")
            return False
    
    def test_connection(self) -> bool:
        """测试Zabbix API连接
        
        Returns:
            连接成功返回True，否则返回False
        """
        if self.mock_mode:
            return True
        
        try:
            if not self._authenticate():
                return False
            
            # 测试基本API调用（已认证状态）
            hosts = self.zapi.host.get(output=['hostid'], limit=1)
            logger.info(f"Zabbix API连接测试成功，获取到 {len(hosts)} 个主机")
            return True
            
        except Exception as e:
            logger.error(f"连接测试失败: {str(e)}")
            return False
    
    def get_host(self, host_ip: str) -> Optional[Dict[str, Any]]:
        """获取主机信息
        
        Args:
            host_ip: 主机IP地址
        
        Returns:
            主机信息字典，如果未找到则返回None
        """
        if self.mock_mode:
            for host in self.mock_hosts:
                if host_ip in host['interfaces'][0]['ip']:
                    return host
            return None
        
        if not self._authenticate():
            return None
        
        try:
            hosts = self.zapi.host.get(
                output=['hostid', 'host', 'name', 'status'],
                selectInterfaces=['ip', 'dns', 'port', 'type', 'main'],
                filter={'ip': [host_ip]}
            )
            return hosts[0] if hosts else None
        except Exception as e:
            logger.error(f"获取主机信息失败: {str(e)}")
            return None
    
    def get_host_by_id(self, host_id: str) -> Optional[Dict[str, Any]]:
        """通过主机ID获取主机信息
        
        Args:
            host_id: 主机ID
        
        Returns:
            主机信息字典，如果未找到则返回None
        """
        if self.mock_mode:
            for host in self.mock_hosts:
                if host['hostid'] == host_id:
                    return host
            return None
        
        if not self._authenticate():
            return None
        
        try:
            hosts = self.zapi.host.get(
                output=['hostid', 'host', 'name', 'status'],
                selectInterfaces=['ip', 'dns', 'port', 'type', 'main'],
                hostids=[host_id]
            )
            return hosts[0] if hosts else None
        except Exception as e:
            logger.error(f"获取主机详情失败: {str(e)}")
            return None

    def get_host_by_name(self, host_name: str) -> Optional[Dict[str, Any]]:
        """通过主机名称获取主机信息

        Args:
            host_name: 主机名称

        Returns:
            主机信息字典，如果未找到则返回None
        """
        if self.mock_mode:
            for host in self.mock_hosts:
                if host['name'] == host_name or host['host'] == host_name:
                    return host
            return None

        if not self._authenticate():
            return None

        try:
            hosts = self.zapi.host.get(
                output=['hostid', 'host', 'name', 'status'],
                selectInterfaces=['ip', 'dns', 'port', 'type', 'main'],
                filter={'name': [host_name]}
            )
            if not hosts:
                hosts = self.zapi.host.get(
                    output=['hostid', 'host', 'name', 'status'],
                    selectInterfaces=['ip', 'dns', 'port', 'type', 'main'],
                    filter={'host': [host_name]}
                )
            return hosts[0] if hosts else None
        except Exception as e:
            logger.error(f"获取主机详情失败: {str(e)}")
            return None

    def get_host_groups(self) -> List[Dict[str, Any]]:
        """获取所有主机组
        
        Returns:
            主机组列表
        """
        if self.mock_mode:
            return [
                {'groupid': '15', 'name': 'Linux servers'},
                {'groupid': '2', 'name': 'Zabbix servers'}
            ]
        
        if not self._authenticate():
            return []
        
        try:
            return self.zapi.hostgroup.get(
                output=['groupid', 'name'],
                selectHosts=['hostid', 'name', 'status']
            )
        except Exception as e:
            logger.error(f"获取主机组失败: {str(e)}")
            return []
    
    def get_templates(self) -> List[Dict[str, Any]]:
        """获取所有模板
        
        Returns:
            模板列表
        """
        if self.mock_mode:
            return [
                {'templateid': '10081', 'name': 'Linux by Zabbix agent'},
                {'templateid': '10047', 'name': 'Agent SNMPv2'}
            ]
        
        if not self._authenticate():
            return []
        
        try:
            return self.zapi.template.get(
                output=['templateid', 'name'],
                selectHosts=['hostid', 'name']
            )
        except Exception as e:
            logger.error(f"获取模板失败: {str(e)}")
            return []
    
    def create_host(self, host_name: str, host_ip: str, group_ids: List[str], template_ids: List[str]) -> Optional[Dict[str, Any]]:
        """创建Zabbix主机
        
        Args:
            host_name: 主机名称
            host_ip: 主机IP地址
            group_ids: 主机组ID列表
            template_ids: 模板ID列表
        
        Returns:
            创建结果，如果失败则返回None
        """
        if self.mock_mode:
            new_hostid = str(int(self.mock_hosts[-1]['hostid']) + 1)
            new_host = {
                'hostid': new_hostid,
                'host': host_name,
                'name': host_name
            }
            self.mock_hosts.append(new_host)
            return {'hostids': [new_hostid]}
        
        if not self._authenticate():
            return None
        
        try:
            interfaces = [{
                'type': 1,
                'main': 1,
                'useip': 1,
                'ip': host_ip,
                'dns': '',
                'port': '10050'
            }]
            
            result = self.zapi.host.create(
                host=host_name,
                interfaces=interfaces,
                groups=[{'groupid': gid} for gid in group_ids],
                templates=[{'templateid': tid} for tid in template_ids],
                inventory_mode=1,
                inventory={
                    'asset_tag': '',
                    'name': host_name
                }
            )
            return result
        except Exception as e:
            logger.error(f"创建主机失败: {str(e)}")
            return None
    
    def delete_host(self, host_id: str = None, host_ip: str = None, host_name: str = None) -> Optional[Dict[str, Any]]:
        """删除Zabbix主机

        Args:
            host_id: 主机ID（可选，如果提供则直接使用）
            host_ip: 主机IP地址（可选，通过IP查找主机后删除）
            host_name: 主机名称（可选，通过名称查找主机后删除）

        Returns:
            删除结果，如果失败则返回None
        """
        if self.mock_mode:
            global mock_hosts
            if host_id:
                self.mock_hosts = [h for h in self.mock_hosts if h['hostid'] != host_id]
            return {'hostids': [host_id] if host_id else []}

        if not self._authenticate():
            logger.error("Zabbix API认证失败")
            return None

        try:
            target_host_id = None

            if host_id:
                target_host_id = int(host_id) if host_id else 0
                if target_host_id <= 0:
                    logger.error(f"无效的host_id: {host_id}")
                    return None
            elif host_ip:
                host_info = self.get_host(host_ip)
                if host_info and 'hostid' in host_info:
                    target_host_id = int(host_info['hostid'])
                    logger.info(f"通过IP {host_ip} 找到主机ID: {target_host_id}")
                else:
                    logger.warning(f"未找到IP为 {host_ip} 的主机，尝试通过名称查找")
                    if host_name:
                        host_info = self.get_host_by_name(host_name)
                        if host_info and 'hostid' in host_info:
                            target_host_id = int(host_info['hostid'])
                            logger.info(f"通过名称 {host_name} 找到主机ID: {target_host_id}")
                        else:
                            logger.error(f"未找到名称为 {host_name} 的主机")
                            return None
                    else:
                        logger.error(f"未找到IP为 {host_ip} 的主机")
                        return None
            elif host_name:
                host_info = self.get_host_by_name(host_name)
                if host_info and 'hostid' in host_info:
                    target_host_id = int(host_info['hostid'])
                    logger.info(f"通过名称 {host_name} 找到主机ID: {target_host_id}")
                else:
                    logger.error(f"未找到名称为 {host_name} 的主机")
                    return None
            else:
                logger.error("未提供host_id、host_ip或host_name参数")
                return None

            result = self.zapi.host.delete(target_host_id)
            logger.info(f"成功删除主机 ID: {target_host_id}")
            return result
        except Exception as e:
            logger.error(f"删除主机失败: {str(e)}")
            return None
    
    def get_items(self, host_id: str, search_key: str = '') -> List[Dict[str, Any]]:
        """获取主机的监控项
        
        Args:
            host_id: 主机ID
            search_key: 可选，搜索关键字
        
        Returns:
            监控项列表
        """
        if self.mock_mode:
            # 返回模拟监控项
            return [
                {
                    'itemid': '34526',
                    'hostid': host_id,
                    'name': 'CPU utilization',
                    'key_': 'system.cpu.util[,utilization]',
                    'lastvalue': '45.5',
                    'units': '%'
                },
                {
                    'itemid': '34527',
                    'hostid': host_id,
                    'name': 'Memory utilization',
                    'key_': 'vm.memory.utilization',
                    'lastvalue': '62.3',
                    'units': '%'
                }
            ]
        
        if not self._authenticate():
            return []
        
        try:
            params = {
                'output': ['itemid', 'hostid', 'name', 'key_', 'lastvalue', 'units'],
                'hostids': [host_id],
                'monitored': True,
                'status': '0'
            }
            
            if search_key:
                if ' ' in search_key:
                    params['search'] = {'name': search_key}
                else:
                    params['search'] = {'key_': search_key}
            
            return self.zapi.item.get(**params)
        except Exception as e:
            logger.error(f"获取监控项失败: {str(e)}")
            return []
    
    def get_host_monitoring_data(self, host_id: str) -> Dict[str, Any]:
        """获取主机的监控数据
        
        Args:
            host_id: 主机ID
        
        Returns:
            监控数据字典
        """
        if self.mock_mode:
            import random
            return {
                'cpu_usage': round(random.uniform(20, 80), 1),
                'memory_usage': round(random.uniform(30, 70), 1),
                'disk_usage': round(random.uniform(40, 60), 1),
                'network_in': round(random.uniform(1000, 10000), 2),
                'network_out': round(random.uniform(500, 5000), 2),
                'load_average_1m': round(random.uniform(0.5, 2.0), 2),
                'load_average_5m': round(random.uniform(0.5, 2.0), 2),
                'load_average_15m': round(random.uniform(0.5, 2.0), 2),
                'uptime': 86400,
                'num_processes': random.randint(100, 200),
                'cpu_cores': 4,
                'system_boot_time': 1640995200,
                'available_memory': 8589934592,
                'total_memory': 17179869184,
                'free_swap': 2147483648,
                'total_swap': 4294967296,
                'logged_in_users': random.randint(1, 3)
            }
        
        if not self._authenticate():
            return {}
        
        data = {
            'cpu_usage': 0.0,
            'memory_usage': 0.0,
            'disk_usage': 0.0,
            'network_in': 0.0,
            'network_out': 0.0,
            'load_average_1m': 0.0,
            'load_average_5m': 0.0,
            'load_average_15m': 0.0,
            'uptime': 0,
            'num_processes': 0,
            'cpu_cores': 0,
            'system_boot_time': 0,
            'available_memory': 0,
            'total_memory': 0,
            'free_swap': 0,
            'total_swap': 0,
            'logged_in_users': 0
        }
        
        try:
            # 获取主机的所有监控项
            all_items = self.zapi.item.get(
                output=['itemid', 'hostid', 'name', 'key_', 'lastvalue', 'units'],
                hostids=[host_id],
                monitored=True,
                status=0
            )
            
            if not all_items:
                return data
            
            # 处理所有监控数据
            for item in all_items:
                name = item.get('name', '')
                lastvalue = item.get('lastvalue', '')
                units = item.get('units', '')
                
                if not name or not lastvalue:
                    continue
                
                try:
                    # 处理CPU使用率
                    if 'CPU utilization' in name:
                        data['cpu_usage'] = round(float(lastvalue), 1)
                    elif 'CPU idle time' in name:
                        data['cpu_usage'] = round(100 - float(lastvalue), 1)
                    
                    # 处理内存使用率
                    elif 'Memory utilization' in name:
                        data['memory_usage'] = round(float(lastvalue), 1)
                    elif 'Available memory in %' in name:
                        data['memory_usage'] = round(100 - float(lastvalue), 1)
                    
                    # 处理可用内存和总内存
                    elif 'Available memory' in name and units == 'B':
                        data['available_memory'] = int(float(lastvalue))
                    elif 'Total memory' in name and units == 'B':
                        data['total_memory'] = int(float(lastvalue))
                    
                    # 处理磁盘使用率
                    elif 'FS [/]: Space: Used, in %' in name:
                        data['disk_usage'] = round(float(lastvalue), 1)
                    
                    # 处理网络流量
                    elif 'Bits received' in name and units == 'bps':
                        data['network_in'] = round(float(lastvalue) / 8, 2)
                    elif 'Bits sent' in name and units == 'bps':
                        data['network_out'] = round(float(lastvalue) / 8, 2)
                    
                    # 处理负载均衡
                    elif 'Load average (1m avg)' in name:
                        data['load_average_1m'] = round(float(lastvalue), 2)
                    elif 'Load average (5m avg)' in name:
                        data['load_average_5m'] = round(float(lastvalue), 2)
                    elif 'Load average (15m avg)' in name:
                        data['load_average_15m'] = round(float(lastvalue), 2)
                    
                    # 处理系统运行时间
                    elif 'System uptime' in name:
                        data['uptime'] = int(float(lastvalue))
                    
                    # 处理系统启动时间
                    elif 'System boot time' in name:
                        data['system_boot_time'] = int(float(lastvalue))
                    
                    # 处理进程数量
                    elif 'Number of processes' in name:
                        data['num_processes'] = int(float(lastvalue))
                    
                    # 处理CPU核心数
                    elif 'Number of CPUs' in name:
                        data['cpu_cores'] = int(float(lastvalue))
                    
                    # 处理交换空间
                    elif 'Free swap space' in name and units == 'B':
                        data['free_swap'] = int(float(lastvalue))
                    elif 'Total swap space' in name and units == 'B':
                        data['total_swap'] = int(float(lastvalue))
                    
                    # 处理登录用户数
                    elif 'Number of logged in users' in name:
                        data['logged_in_users'] = int(float(lastvalue))
                    
                except (ValueError, TypeError):
                    # 只在开发环境打印错误，生产环境跳过
                    logger.debug(f"处理监控数据失败: {str(e)}")
                    
        except Exception as e:
            logger.error(f"获取监控数据失败: {str(e)}")
        
        return data
    
    def get_active_problems(self, host_ids: Optional[List[str]] = None, recent: bool = False) -> List[Dict[str, Any]]:
        """获取活跃问题

        Args:
            host_ids: 可选，主机ID列表
            recent: 是否包含最近已恢复的问题（False=仅真正活跃的未恢复告警）

        Returns:
            问题列表，包含 hosts 字段用于关联服务器
        """
        if self.mock_mode:
            for p in self.mock_problems:
                p['hosts'] = [{'hostid': '10084'}]
            return self.mock_problems

        if not self._authenticate():
            return []

        try:
            params = {
                'output': ['eventid', 'name', 'clock', 'severity', 'acknowledged', 'objectid', 'r_eventid'],
                'sortfield': ['eventid'],
                'sortorder': 'DESC',
                'limit': 500
            }

            if host_ids:
                params['hostids'] = host_ids[:50]

            if recent:
                params['recent'] = True

            problems = self.zapi.problem.get(**params)

            # problem.get doesn't support selectHosts — resolve host mapping via triggers
            if problems:
                triggerids = [p.get('objectid') for p in problems if p.get('objectid')]
                if triggerids:
                    triggers = self.zapi.trigger.get(
                        output=['triggerid'],
                        triggerids=triggerids,
                        selectHosts=['hostid', 'host', 'name']
                    )
                    trigger_host_map = {}
                    for t in triggers:
                        trigger_host_map[t['triggerid']] = t.get('hosts', [])

                    for problem in problems:
                        objectid = problem.get('objectid')
                        problem['hosts'] = trigger_host_map.get(objectid, [])

            return problems
        except Exception as e:
            logger.error(f"获取活跃问题失败: {str(e)}")
            return []
    
    def get_host_alerts(self, host_id: str) -> List[Dict[str, Any]]:
        """获取主机的活跃告警（仅未恢复的）

        Args:
            host_id: 主机ID

        Returns:
            活跃告警列表，包含 hosts 字段
        """
        try:
            if not self._authenticate():
                return []

            problems = self.zapi.problem.get(
                output=['eventid', 'name', 'clock', 'severity', 'acknowledged', 'objectid', 'r_eventid'],
                hostids=[host_id],
                recent=False,
                sortfield=['eventid'],
                sortorder='DESC'
            )

            # Resolve host mapping via triggers
            if problems:
                triggerids = [p.get('objectid') for p in problems if p.get('objectid')]
                if triggerids:
                    triggers = self.zapi.trigger.get(
                        output=['triggerid'],
                        triggerids=triggerids,
                        selectHosts=['hostid', 'host', 'name']
                    )
                    trigger_host_map = {}
                    for t in triggers:
                        trigger_host_map[t['triggerid']] = t.get('hosts', [])

                    for problem in problems:
                        objectid = problem.get('objectid')
                        problem['hosts'] = trigger_host_map.get(objectid, [])

            return problems if problems else []
        except Exception as e:
            logger.error(f"获取主机告警信息失败: {str(e)}")
            return []
    
    def get_host_history_data(self, host_id: str, hours: int = 1) -> Dict[str, Any]:
        """获取主机的历史监控数据
        
        Args:
            host_id: 主机ID
            hours: 获取最近多少小时的数据
        
        Returns:
            历史数据字典
        """
        if self.mock_mode:
            import time
            import random
            
            data = {
                'cpu_history': [],
                'memory_history': [],
                'timestamps': []
            }
            
            current_time = int(time.time())
            start_time = current_time - hours * 3600
            
            # 生成模拟数据
            for i in range(0, hours * 60, 5):  # 每5分钟一个数据点
                timestamp = start_time + i * 60
                data['timestamps'].append(timestamp)
                data['cpu_history'].append(round(10 + (i % 50), 1))
                data['memory_history'].append(round(20 + (i % 60), 1))
            
            return data
        
        data = {
            'cpu_history': [],
            'memory_history': [],
            'timestamps': []
        }
        
        try:
            if not self._authenticate():
                return data
            
            # 1. 获取主机的所有监控项
            all_items = self.zapi.item.get(
                output=['itemid', 'hostid', 'name', 'key_'],
                hostids=[host_id],
                monitored=True,
                status=0
            )
            
            if not all_items:
                logger.warning(f"未找到主机{host_id}的监控项")
                return data
            
            # 2. 查找CPU和内存监控项
            cpu_item = None
            memory_item = None
            
            for item in all_items:
                name = item.get('name', '')
                key_ = item.get('key_', '')
                
                # 查找CPU使用率相关监控项
                if not cpu_item:
                    if 'CPU utilization' in name or 'cpu.util' in key_:
                        cpu_item = item
                    elif 'CPU idle time' in name:
                        cpu_item = item
                    elif key_ in ['system.cpu.util[,utilization]', 'system.cpu.util[,idle]']:
                        cpu_item = item
                
                # 查找内存使用率相关监控项
                if not memory_item:
                    if 'Memory utilization' in name:
                        memory_item = item
                    elif 'Available memory in %' in name:
                        memory_item = item
                    elif 'vm.memory.utilization' in key_:
                        memory_item = item
                    elif 'vm.memory.util' in key_:
                        memory_item = item
            
            # 3. 获取历史数据
            if cpu_item and memory_item:
                # 计算时间范围
                import time
                end_time = int(time.time())
                start_time = end_time - hours * 3600
                
                # 获取CPU历史数据
                cpu_history = self.zapi.history.get(
                    output=['clock', 'value'],
                    itemids=[cpu_item['itemid']],
                    time_from=start_time,
                    time_till=end_time,
                    history=0,  # numeric float
                    sortfield='clock',
                    sortorder='ASC'
                )
                
                # 获取内存历史数据
                memory_history = self.zapi.history.get(
                    output=['clock', 'value'],
                    itemids=[memory_item['itemid']],
                    time_from=start_time,
                    time_till=end_time,
                    history=0,  # numeric float
                    sortfield='clock',
                    sortorder='ASC'
                )
                
                # 处理历史数据
                if cpu_history:
                    # 创建内存数据映射
                    memory_map = {}
                    if memory_history:
                        for record in memory_history:
                            if 'clock' in record and 'value' in record:
                                try:
                                    memory_map[int(record['clock'])] = float(record['value'])
                                except (ValueError, TypeError):
                                    pass
                    
                    # 处理CPU数据并同步内存数据
                    for record in cpu_history:
                        if 'clock' in record and 'value' in record:
                            try:
                                timestamp = int(record['clock'])
                                cpu_value = float(record['value'])
                                
                                # 计算CPU使用率
                                if 'idle' in cpu_item['name'].lower() or 'idle' in cpu_item.get('key_', '').lower():
                                    cpu_usage = round(100 - cpu_value, 1)
                                else:
                                    cpu_usage = round(cpu_value, 1)
                                
                                # 计算内存使用率
                                memory_usage = 0.0
                                if timestamp in memory_map:
                                    memory_value = memory_map[timestamp]
                                    if 'Available memory' in memory_item['name'] or 'available' in memory_item.get('key_', '').lower() or 'pavailable' in memory_item.get('key_', '').lower():
                                        memory_usage = round(100 - memory_value, 1)
                                    else:
                                        memory_usage = round(memory_value, 1)
                                
                                # 添加到结果数据中
                                data['cpu_history'].append(cpu_usage)
                                data['memory_history'].append(memory_usage)
                                data['timestamps'].append(timestamp)
                            except (ValueError, TypeError) as e:
                                logger.debug(f"处理历史数据失败: {str(e)}")
            
        except Exception as e:
            logger.error(f"获取历史数据失败: {str(e)}")
        
        return data