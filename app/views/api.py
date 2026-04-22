from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.server import Server
from app.models.task import Task

# 创建蓝图
api_bp = Blueprint('api', __name__)

# 用户相关API
@api_bp.route('/auth/register', methods=['POST'])
def register():
    """用户注册API"""
    data = request.get_json()
    # 实现注册逻辑
    return jsonify({'message': '注册成功'})

@api_bp.route('/auth/login', methods=['POST'])
def login():
    """用户登录API"""
    data = request.get_json()
    # 实现登录逻辑
    return jsonify({'message': '登录成功'})

@api_bp.route('/users', methods=['GET'])
@login_required
def get_users():
    """获取用户列表API"""
    users = User.query.all()
    return jsonify([{
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'role': user.role
    } for user in users])

# 服务器相关API
@api_bp.route('/servers', methods=['GET'])
@login_required
def get_servers():
    """获取服务器列表API"""
    servers = Server.query.all()
    return jsonify([{
        'id': server.id,
        'name': server.name,
        'ip': server.ip,
        'port': server.port,
        'status': server.status
    } for server in servers])

# 监控相关API - 已弃用，请使用 /log/api/search
@api_bp.route('/monitor/alerts', methods=['GET'])
@login_required
def get_alerts():
    """获取告警列表API - 已弃用"""
    return jsonify({'message': 'Alert API已弃用，请使用日志搜索功能', 'deprecated': True})

# 日志相关API - 已弃用，请使用 /log/api/search
@api_bp.route('/logs', methods=['GET'])
@login_required
def get_logs():
    """获取日志列表API - 已弃用"""
    return jsonify({'message': 'Log API已弃用，请使用 /log/api/search', 'deprecated': True})

# 配置相关API
@api_bp.route('/config/env', methods=['GET'])
@login_required
def get_env_config():
    """获取前端可访问的环境变量配置"""
    from app.config import Config
    
    env_config = {
        'ZABBIX_URL': Config.get('ZABBIX_URL', ''),
        'ZABBIX_TOKEN': Config.get('ZABBIX_TOKEN', ''),
        'AI_API_KEY': Config.get('AI_API_KEY', ''),
        'AI_API_URL': Config.get('AI_API_URL', ''),
        'MAIL_SERVER': Config.get('MAIL_SERVER', ''),
        'MAIL_USERNAME': Config.get('MAIL_USERNAME', ''),
        'BACKUP_DIR': Config.get('BACKUP_DIR', ''),
        'BACKUP_INTERVAL': Config.get('BACKUP_INTERVAL', ''),
    }
    
    return jsonify(env_config)

# AI相关API
@api_bp.route('/ai/generate-command', methods=['POST'])
@login_required
def generate_command():
    """AI生成Linux命令"""
    from app.config import Config
    import json
    import httpx
    from flask import current_app
    
    Config.init_app_config(current_app)
    
    try:
        data = request.get_json()
        
        if not data or 'prompt' not in data:
            return jsonify({
                'success': False,
                'message': '请提供命令描述'
            }), 400
        
        prompt = data['prompt'].strip()
        
        if len(prompt) < 3:
            return jsonify({
                'success': False,
                'message': '描述太短，请提供更详细的信息'
            }), 400
        
        if len(prompt) > 500:
            return jsonify({
                'success': False,
                'message': '描述太长，请简化'
            }), 400
        
        api_key = Config.get('AI_API_KEY', '')
        api_url = Config.get('AI_API_URL', 'https://api.deepseek.com/v1/chat/completions')
        
        if not api_key:
            return jsonify({
                'success': False,
                'message': 'AI API密钥未配置，请先在系统设置中配置 AI_API_KEY'
            }), 500
        
        system_prompt = """你是一个Linux运维命令助手。用户会用中文描述他们想要执行的运维操作，你需要生成对应的Linux命令。

要求：
1. 只返回可执行的命令，不要返回任何解释、注释或格式标记
2. 如果需要多个命令，使用 && 分隔
3. 命令要完整且可直接执行
4. 考虑安全性，避免生成危险的命令
5. 如果用户的描述不清晰，返回一个最可能的命令

示例输入：查看CPU使用率
示例输出：top -bn1 | head -5

现在根据用户的描述生成命令："""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": 200,
            "temperature": 0.3
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(api_url, json=payload, headers=headers)
            
            if response.status_code != 200:
                current_app.logger.error(f"AI API error: {response.text}")
                return jsonify({
                    'success': False,
                    'message': f'AI 服务响应错误: {response.status_code}'
                }), 500
            
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                generated_command = result['choices'][0]['message']['content'].strip()
                
                cleaned_command = generated_command
                import re
                code_patterns = [
                    (r'```[a-z]*\n?(.*?)\n?```', r'\1'),
                    (r'`([^`]+)`', r'\1'),
                    (r'^Command:\s*', r''),
                    (r'^命令:\s*', r''),
                ]
                for pattern, replacement in code_patterns:
                    cleaned_command = re.sub(pattern, replacement, cleaned_command, flags=re.MULTILINE | re.DOTALL).strip()
                
                cleaned_command = '\n'.join(line.strip() for line in cleaned_command.split('\n') if line.strip())
                
                return jsonify({
                    'success': True,
                    'command': cleaned_command,
                    'raw_response': generated_command
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'AI未能生成有效的命令'
                }), 500
                
    except httpx.TimeoutException:
        current_app.logger.error("AI API timeout")
        return jsonify({
            'success': False,
            'message': 'AI 服务请求超时，请稍后再试'
        }), 500
    except Exception as e:
        current_app.logger.error(f"AI command generation error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'AI 服务暂时不可用: {str(e)}'
        }), 500