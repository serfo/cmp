import requests
import json
import markdown
from app.config import Config

class AIAnalyzer:
    """AI分析器，用于调用DeepSeek API进行分析"""
    
    def __init__(self):
        # 从配置中获取API密钥和URL
        self.api_key = Config.AI_API_KEY
        self.api_url = Config.AI_API_URL
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
    
    def analyze_log(self, log_content, analysis_type='root_cause'):
        """分析日志
        
        Args:
            log_content: 要分析的日志内容
            analysis_type: 分析类型，可选值：error_detection, root_cause, solution, optimization
        
        Returns:
            分析结果字典，包含conclusion、suggestions、raw_response等键
        """
        if not log_content:
            result = {
                'conclusion': '无日志内容可分析',
                'suggestions': ['请提供有效的日志内容'],
                'confidence': 0.0,
                'raw_response': '无日志内容可分析',
                'html_content': '<p>无日志内容可分析</p>'
            }
            return result
        
        # 构建分析类型对应的提示词
        prompt_templates = {
            'error_detection': '请分析以下日志，指出其中包含的错误和警告信息：',
            'root_cause': '请分析以下日志，找出错误的根本原因：',
            'solution': '请分析以下日志，提供解决方案：',
            'optimization': '请分析以下日志，提供系统优化建议：'
        }
        
        prompt = prompt_templates.get(analysis_type, prompt_templates['root_cause'])
        
        # 构建请求体（DeepSeek API格式）
        data = {
            'model': 'deepseek-chat',
            'messages': [
                {
                    'role': 'system',
                    'content': '你是一位经验丰富的系统管理员和运维专家，擅长分析各种系统日志，找出问题并提供解决方案。请用中文回答，保持回答简洁明了，重点突出。'
                },
                {
                    'role': 'user',
                    'content': f'{prompt}\n\n{log_content}'
                }
            ],
            'temperature': 0.7,
            'max_tokens': 7000
        }
        
        try:
            # 打印请求详细信息，用于排错
            print(f"AI API请求URL: {self.api_url}")
            print(f"AI API请求方法: POST")
            # 打印headers，但不显示完整的API密钥
            safe_headers = self.headers.copy()
            if 'Authorization' in safe_headers:
                safe_headers['Authorization'] = safe_headers['Authorization'][:20] + '...'
            print(f"AI API请求headers: {safe_headers}")
            print(f"AI API请求body: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            response = requests.post(self.api_url, headers=self.headers, json=data, timeout=30)
            print(f"AI API响应状态码: {response.status_code}")
            print(f"AI API响应headers: {response.headers}")
            print(f"AI API响应内容: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                return self._parse_response(content)
            else:
                result = {
                    'conclusion': 'AI分析失败',
                    'suggestions': ['请检查API配置或重试'],
                    'confidence': 0.0,
                    'raw_response': 'AI分析失败，请检查API配置或重试',
                    'html_content': '<p>AI分析失败，请检查API配置或重试</p>'
                }
                return result
        except Exception as e:
            print(f"日志分析失败: {e}")
            result = {
                'conclusion': 'AI分析失败',
                'suggestions': ['无法获取分析结果'],
                'confidence': 0.0,
                'raw_response': 'AI分析失败，无法获取分析结果',
                'html_content': '<p>AI分析失败，无法获取分析结果</p>'
            }
            return result
    
    def analyze_server_config(self, server_info):
        """分析服务器配置"""
        if not server_info:
            result = {
                'conclusion': '无服务器配置可分析',
                'suggestions': ['请提供有效的服务器配置'],
                'confidence': 0.0,
                'raw_response': '无服务器配置可分析',
                'html_content': '<p>无服务器配置可分析</p>'
            }
            return result
        
        prompt = f"""请分析以下服务器配置，给出优化建议：

{server_info}

分析要求：
1. 评估当前配置合理性
2. 识别潜在瓶颈
3. 提供具体的优化建议
4. 考虑性能、安全和稳定性
"""
        
        data = {
            'model': 'deepseek-chat',
            'messages': [
                {
                    'role': 'system',
                    'content': '你是一位经验丰富的系统管理员和运维专家，擅长分析服务器配置并提供优化建议。请用中文回答，保持回答简洁明了，重点突出。'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'temperature': 0.7,
            'max_tokens': 7000
        }
        
        try:
            # 打印请求详细信息，用于排错
            print(f"AI API请求URL: {self.api_url}")
            print(f"AI API请求方法: POST")
            # 打印headers，但不显示完整的API密钥
            safe_headers = self.headers.copy()
            if 'Authorization' in safe_headers:
                safe_headers['Authorization'] = safe_headers['Authorization'][:20] + '...'
            print(f"AI API请求headers: {safe_headers}")
            print(f"AI API请求body: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            response = requests.post(self.api_url, headers=self.headers, json=data, timeout=30)
            print(f"AI API响应状态码: {response.status_code}")
            print(f"AI API响应headers: {response.headers}")
            print(f"AI API响应内容: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                return self._parse_response(content)
            else:
                result = {
                    'conclusion': 'AI分析失败',
                    'suggestions': ['请检查API配置或重试'],
                    'confidence': 0.0,
                    'raw_response': 'AI分析失败，请检查API配置或重试',
                    'html_content': '<p>AI分析失败，请检查API配置或重试</p>'
                }
                return result
        except Exception as e:
            print(f"配置分析失败: {e}")
            result = {
                'conclusion': 'AI分析失败',
                'suggestions': ['无法获取分析结果'],
                'confidence': 0.0,
                'raw_response': 'AI分析失败，无法获取分析结果',
                'html_content': '<p>AI分析失败，无法获取分析结果</p>'
            }
            return result
    
    def analyze_server_monitoring_data(self, monitoring_data, selected_items, analysis_type='summary'):
        """分析服务器监控数据
        
        Args:
            monitoring_data: 服务器监控数据
            selected_items: 选中的分析项
            analysis_type: 分析类型，可选值：summary, suggestion, troubleshoot
        
        Returns:
            分析结果字典，包含conclusion、suggestions、raw_response等键
        """
        # 构建要分析的内容
        analysis_content = f"# 服务器AI分析请求\n\n"
        
        # 添加基本信息
        if 'basic_info' in selected_items:
            server_data = monitoring_data.get('server_data', {})
            analysis_content += f"## 基本信息\n"
            analysis_content += f"- 服务器名称: {server_data.get('name', '未知')}\n"
            analysis_content += f"- IP地址: {server_data.get('ip', '未知')}\n"
            analysis_content += f"- CPU核心数: {server_data.get('cpu_cores', '未知')}\n"
            analysis_content += f"- 内存: {server_data.get('memory', '未知')} GB\n"
            analysis_content += f"- 磁盘: {server_data.get('disk', '未知')} GB\n\n"
        
        # 添加CPU内存网络使用率
        if 'cpu_memory_network' in selected_items:
            analysis_content += f"## CPU内存网络使用率\n"
            analysis_content += f"- CPU使用率: {monitoring_data.get('cpu_usage', 0)}%\n"
            analysis_content += f"- 内存使用率: {monitoring_data.get('memory_usage', 0)}%\n"
            analysis_content += f"- 磁盘使用率: {monitoring_data.get('disk_usage', 0)}%\n"
            analysis_content += f"- 网络入流量: {monitoring_data.get('network_in', 0)} B/s\n"
            analysis_content += f"- 网络出流量: {monitoring_data.get('network_out', 0)} B/s\n\n"
        
        # 添加负载率
        if 'load_rate' in selected_items:
            analysis_content += f"## 负载率\n"
            analysis_content += f"- 1分钟平均负载: {monitoring_data.get('load_average_1m', 0)}\n"
            analysis_content += f"- 5分钟平均负载: {monitoring_data.get('load_average_5m', 0)}\n"
            analysis_content += f"- 15分钟平均负载: {monitoring_data.get('load_average_15m', 0)}\n\n"
        
        # 添加系统详细信息
        if 'system_details' in selected_items:
            analysis_content += f"## 系统详细信息\n"
            analysis_content += f"- 进程数量: {monitoring_data.get('num_processes', 0)}\n"
            analysis_content += f"- 登录用户数: {monitoring_data.get('logged_in_users', 0)}\n"
            analysis_content += f"- 可用内存: {monitoring_data.get('available_memory', 0)} B\n"
            analysis_content += f"- 总内存: {monitoring_data.get('total_memory', 0)} B\n"
            analysis_content += f"- 总交换空间: {monitoring_data.get('total_swap', 0)} B\n"
            analysis_content += f"- 可用交换空间: {monitoring_data.get('free_swap', 0)} B\n\n"
        
        # 添加服务器告警
        if 'alerts' in selected_items:
            selected_alerts = monitoring_data.get('selected_alerts', [])
            analysis_content += f"## 服务器告警\n"
            if selected_alerts:
                for alert in selected_alerts:
                    analysis_content += f"- {alert.get('created_at', '')}: {alert.get('message', '')}\n"
            else:
                analysis_content += f"- 暂无告警\n"
            analysis_content += f"\n"
        
        # 获取分析类型对应的提示词
        prompt_templates = {
            'summary': '请对以下服务器监控数据生成一份简要摘要：',
            'suggestion': '请根据以下服务器监控数据生成优化建议：',
            'troubleshoot': '请根据以下服务器监控数据进行故障排查分析：'
        }
        
        prompt = prompt_templates.get(analysis_type, prompt_templates['summary'])
        
        # 构建完整的分析请求
        full_prompt = f"{prompt}\n\n{analysis_content}"
        
        # 构建请求体
        data = {
            'model': 'deepseek-chat',
            'messages': [
                {
                    'role': 'system',
                    'content': '你是一位经验丰富的系统管理员和运维专家，擅长分析服务器监控数据，提供优化建议和故障排查。请用中文回答，保持回答简洁明了，重点突出。'
                },
                {
                    'role': 'user',
                    'content': full_prompt
                }
            ],
            'temperature': 0.7,
            'max_tokens': 7000
        }
        
        try:
            # 打印请求详细信息，用于排错
            print(f"AI API请求URL: {self.api_url}")
            print(f"AI API请求方法: POST")
            # 打印headers，但不显示完整的API密钥
            safe_headers = self.headers.copy()
            if 'Authorization' in safe_headers:
                safe_headers['Authorization'] = safe_headers['Authorization'][:20] + '...'
            print(f"AI API请求headers: {safe_headers}")
            print(f"AI API请求body: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            response = requests.post(self.api_url, headers=self.headers, json=data, timeout=30)
            print(f"AI API响应状态码: {response.status_code}")
            print(f"AI API响应headers: {response.headers}")
            print(f"AI API响应内容: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                return self._parse_response(content)
            else:
                result = {
                    'conclusion': 'AI分析失败',
                    'suggestions': ['请检查API配置或重试'],
                    'confidence': 0.0,
                    'raw_response': 'AI分析失败，请检查API配置或重试',
                    'html_content': '<p>AI分析失败，请检查API配置或重试</p>'
                }
                return result
        except Exception as e:
            print(f"服务器监控数据分析失败: {e}")
            result = {
                'conclusion': 'AI分析失败',
                'suggestions': ['无法获取分析结果'],
                'confidence': 0.0,
                'raw_response': 'AI分析失败，无法获取分析结果',
                'html_content': '<p>AI分析失败，无法获取分析结果</p>'
            }
            return result
    
    def _parse_response(self, content):
        """解析AI响应，提取结论和建议
        
        Args:
            content: AI返回的原始内容
        
        Returns:
            分析结果字典，包含conclusion和suggestions
        """
        # 解析Markdown内容
        html_content = markdown.markdown(content)
        
        lines = content.split('\n')
        conclusion = ''
        suggestions = []
        in_suggestions = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 检测建议开始
            if line.startswith('建议') or line.startswith('解决方案') or line.startswith('优化建议') or line.startswith('总结'):
                in_suggestions = True
                continue
            
            # 处理列表项
            if in_suggestions:
                if line.startswith('- ') or line.startswith('1.') or line.startswith('2.') or line.startswith('3.'):
                    # 移除列表标记
                    suggestion = line[2:].strip() if line.startswith('- ') else line.split('.', 1)[1].strip()
                    suggestions.append(suggestion)
            else:
                # 积累结论
                conclusion += line + ' '
        
        # 如果没有提取到建议，尝试从整个内容中提取
        if not suggestions:
            # 简单处理，将整个内容作为结论
            suggestions = ['请查看详细分析']
        
        conclusion = conclusion.strip()
        
        return {
            'conclusion': conclusion if conclusion else content.split('\n')[0],
            'suggestions': suggestions,
            'confidence': 0.9,
            'raw_response': content,
            'html_content': html_content
        }
    
    def analyze_logs(self, logs):
        """兼容旧版API的日志分析方法"""
        result = self.analyze_log(logs, analysis_type='root_cause')
        return result['raw_response']