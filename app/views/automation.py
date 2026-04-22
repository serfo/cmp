from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from app import db, scheduler
from app.models.task import Task, TaskLog
from app.models.server import Server
from app import execute_task
import json
from datetime import datetime

# 创建蓝图
automation_bp = Blueprint('automation', __name__)

@automation_bp.route('/')
@login_required
def index():
    """自动化任务列表"""
    tasks = Task.query.all()
    return render_template('automation/index.html', tasks=tasks)

@automation_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """添加自动化任务"""
    servers = Server.query.all()
    
    # 从URL参数获取预填充数据
    prefill_data = {
        'name': request.args.get('name', ''),
        'task_type': request.args.get('task_type', ''),
        'command': request.args.get('command', '')
    }
    
    # 获取AI原始输入
    ai_prompt = request.args.get('ai_prompt', '')
    
    if request.method == 'POST':
        name = request.form['name']
        task_type = request.form['task_type']
        cron_expression = request.form['cron_expression']
        command = request.form['command']
        timeout = int(request.form['timeout']) if request.form['timeout'] else 3600
        
        # 获取选中的服务器
        selected_servers = request.form.getlist('target_servers')
        target_servers = json.dumps(selected_servers)
        
        # 创建新任务
        new_task = Task(
            name=name,
            task_type=task_type,
            cron_expression=cron_expression,
            command=command,
            ai_prompt=request.form.get('ai_prompt', ai_prompt),
            target_servers=target_servers,
            timeout=timeout,
            created_by=current_user.id
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        # 如果有定时表达式，添加到调度器
        if cron_expression:
            from apscheduler.triggers.cron import CronTrigger
            scheduler.add_job(
                func=execute_task,
                trigger=CronTrigger.from_crontab(cron_expression),
                args=[current_app._get_current_object(), new_task.id],
                id=f'task_{new_task.id}',
                replace_existing=True
            )
        
        flash('任务添加成功', 'success')
        return redirect(url_for('automation.index'))
    
    return render_template('automation/add.html', servers=servers, prefill_data=prefill_data, ai_prompt=ai_prompt)

@automation_bp.route('/run/<int:id>')
@login_required
def run(id):
    """执行自动化任务"""
    task = Task.query.get_or_404(id)
    
    # 调用execute_task函数执行任务
    from app import execute_task
    import threading
    
    # 创建线程异步执行任务
    thread = threading.Thread(target=execute_task, args=(current_app._get_current_object(), id), daemon=True)
    thread.start()
    
    flash('任务已开始执行', 'success')
    return redirect(url_for('automation.index'))

@automation_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    """编辑自动化任务"""
    task = Task.query.get_or_404(id)
    servers = Server.query.all()
    old_cron = task.cron_expression
    
    # 解析已选服务器
    if task.target_servers:
        try:
            selected_servers = json.loads(task.target_servers)
        except json.JSONDecodeError:
            selected_servers = []
    else:
        selected_servers = []
    
    if request.method == 'POST':
        task.name = request.form['name']
        task.task_type = request.form['task_type']
        new_cron = request.form['cron_expression']
        task.cron_expression = new_cron
        task.command = request.form['command']
        task.timeout = int(request.form['timeout']) if request.form['timeout'] else 3600
        
        # 获取选中的服务器
        selected_servers = request.form.getlist('target_servers')
        task.target_servers = json.dumps(selected_servers)
        
        db.session.commit()
        
        # 更新调度器中的任务
        job_id = f'task_{task.id}'
        if scheduler.get_job(job_id):
            # 删除旧任务
            scheduler.remove_job(job_id)
        
        # 如果有新的定时表达式，添加到调度器
        if new_cron:
            from apscheduler.triggers.cron import CronTrigger
            scheduler.add_job(
                func=execute_task,
                trigger=CronTrigger.from_crontab(new_cron),
                args=[current_app._get_current_object(), task.id],
                id=job_id,
                replace_existing=True
            )
        
        flash('任务更新成功', 'success')
        return redirect(url_for('automation.index'))
    
    return render_template('automation/edit.html', task=task, servers=servers, selected_servers=selected_servers)

@automation_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    """删除自动化任务"""
    task = Task.query.get_or_404(id)
    
    # 从调度器中删除任务
    job_id = f'task_{task.id}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # 从数据库中删除任务
    db.session.delete(task)
    db.session.commit()
    flash('任务删除成功', 'success')
    return redirect(url_for('automation.index'))

@automation_bp.route('/logs/<int:id>')
@login_required
def logs(id):
    """查看任务日志"""
    task = Task.query.get_or_404(id)
    logs = TaskLog.query.filter_by(task_id=id).order_by(TaskLog.created_at.desc()).all()
    return render_template('automation/logs.html', task=task, logs=logs)

@automation_bp.route('/api/ai/analyze/<int:id>', methods=['POST'])
@login_required
def ai_analyze_task(id):
    """AI分析任务执行结果"""
    from app.config import Config
    import httpx
    from flask import current_app
    
    Config.init_app_config(current_app)
    
    try:
        task = Task.query.get_or_404(id)
        logs = TaskLog.query.filter_by(task_id=id).order_by(TaskLog.created_at.asc()).all()
        
        if not logs:
            return jsonify({
                'success': False,
                'message': '没有日志数据可供分析'
            }), 400
        
        api_key = Config.get('AI_API_KEY', '')
        api_url = Config.get('AI_API_URL', 'https://api.deepseek.com/v1/chat/completions')
        
        if not api_key:
            return jsonify({
                'success': False,
                'message': 'AI API密钥未配置，无法进行分析'
            }), 500
        
        log_data = []
        for log in logs:
            log_data.append({
                'timestamp': log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'status': log.status,
                'message': log.message or '',
                'output': log.output or ''
            })
        
        analysis_prompt = f"""你是一个专业的运维分析专家。请对以下自动化任务执行结果进行全面分析：

## 任务基本信息
- 任务名称: {task.name}
- 任务类型: {task.task_type}
- 任务ID: {task.id}
- 创建时间: {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}

## 用户原始需求（AI助手输入）
{f'用户描述：{task.ai_prompt}' if task.ai_prompt else '无AI助手输入记录'}

## 执行的命令
{task.command}

## 目标服务器
{task.target_servers}

## 执行日志（共{len(logs)}条）
"""
        
        for log in log_data:
            analysis_prompt += f"""
时间: {log['timestamp']}
状态: {log['status']}
消息: {log['message']}
输出: {log['output'][:500] if log['output'] else '无'}
---
"""
        
        analysis_prompt += """
请根据以上信息，生成一份结构化的分析报告，包括以下维度：

1. **执行概览**
   - 总体成功率
   - 执行时长
   - 影响范围

2. **关键节点分析**
   - 重要的时间节点
   - 状态变化点
   - 可能的瓶颈

3. **问题识别**
   - 失败原因分析（如果有）
   - 潜在风险点
   - 异常模式识别

4. **用户需求匹配度**
   - 用户原始需求
   - 执行结果对比
   - 匹配度评分（0-100）

5. **优化建议**
   - 命令优化建议
   - 错误处理建议
   - 效率提升建议

6. **总结**
   - 整体评估
   - 是否需要人工干预

请用JSON格式输出，结构如下：
{
  "summary": {
    "total_logs": int,
    "success_count": int,
    "failed_count": int,
    "execution_duration": "string",
    "success_rate": float
  },
  "key_nodes": [
    {"time": "string", "event": "string", "significance": "high/medium/low"}
  ],
  "issues": [
    {
      "type": "error/warning/risk",
      "description": "string",
      "severity": "high/medium/low",
      "recommendation": "string"
    }
  ],
  "match_analysis": {
    "user_intent": "string",
    "actual_result": "string",
    "match_score": int,
    "analysis": "string"
  },
  "optimization": {
    "command_suggestions": ["string"],
    "error_handling": ["string"],
    "efficiency_tips": ["string"]
  },
  "conclusion": {
    "overall_assessment": "string",
    "needs_human_review": boolean,
    "action_items": ["string"]
  }
}
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的运维分析专家，擅长分析任务执行结果并提供优化建议。请始终以JSON格式输出分析结果。"},
            {"role": "user", "content": analysis_prompt}
        ]
        
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.3
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        with httpx.Client(timeout=60.0) as client:
            response = client.post(api_url, json=payload, headers=headers)
            
            if response.status_code != 200:
                current_app.logger.error(f"AI Analysis API error: {response.text}")
                return jsonify({
                    'success': False,
                    'message': f'AI 服务响应错误: {response.status_code}'
                }), 500
            
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                analysis_content = result['choices'][0]['message']['content'].strip()
                
                import json as json_mod
                import re
                
                code_pattern = r'```json?\n?(.*?)\n?```'
                match = re.search(code_pattern, analysis_content, re.DOTALL)
                if match:
                    analysis_content = match.group(1).strip()
                
                try:
                    analysis_data = json_mod.loads(analysis_content)
                    return jsonify({
                        'success': True,
                        'analysis': analysis_data,
                        'raw_response': result['choices'][0]['message']['content']
                    })
                except json_mod.JSONDecodeError:
                    return jsonify({
                        'success': True,
                        'analysis_text': analysis_content,
                        'raw_response': result['choices'][0]['message']['content']
                    })
            else:
                return jsonify({
                    'success': False,
                    'message': 'AI未能生成有效的分析结果'
                }), 500
                
    except httpx.TimeoutException:
        current_app.logger.error("AI Analysis API timeout")
        return jsonify({
            'success': False,
            'message': 'AI 分析请求超时，请稍后再试'
        }), 500
    except Exception as e:
        current_app.logger.error(f"AI analysis error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'AI 分析服务暂时不可用: {str(e)}'
        }), 500

@automation_bp.route('/api/ai/analyze-log/<int:log_id>', methods=['POST'])
@login_required
def ai_analyze_single_log(log_id):
    """AI分析单条任务日志"""
    from app.config import Config
    import httpx
    from flask import current_app
    
    Config.init_app_config(current_app)
    
    try:
        task_log = TaskLog.query.get_or_404(log_id)
        task = Task.query.get(task_log.task_id)
        
        if not task:
            return jsonify({
                'success': False,
                'message': '未找到关联任务'
            }), 404
        
        api_key = Config.get('AI_API_KEY', '')
        api_url = Config.get('AI_API_URL', 'https://api.deepseek.com/v1/chat/completions')
        
        if not api_key:
            return jsonify({
                'success': False,
                'message': 'AI API密钥未配置，无法进行分析'
            }), 500
        
        analysis_prompt = f"""你是一个专业的运维分析专家。请对以下单条自动化任务日志进行详细分析：

## 任务基本信息
- 任务名称: {task.name}
- 任务类型: {task.task_type}
- 任务ID: {task.id}
- 任务创建时间: {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}

## 用户原始需求（AI助手输入）
{f'用户描述：{task.ai_prompt}' if task.ai_prompt else '无AI助手输入记录，用户手动创建任务或使用预设命令'}

## 执行的命令
{task.command}

## 目标服务器
{task.target_servers}

## 单条日志详情
- 日志ID: {task_log.id}
- 状态: {task_log.status}
- 执行时间: {task_log.created_at.strftime('%Y-%m-%d %H:%M:%S')}
- 消息: {task_log.message or '无'}
- 输出: {task_log.output or '无输出'}

请根据以上信息，生成一份针对单条日志的详细分析报告，包含以下四个核心部分：

1. **关键节点分析**
   - 分析该日志中的关键执行步骤
   - 识别重要的执行节点和时间点
   - 标记可能的执行瓶颈或异常点

2. **需求匹配度分析**
   - 对比用户原始需求与实际执行结果
   - 评估命令是否有效达成了预期目标
   - 计算匹配度评分（0-100）

3. **执行总结**
   - 简明扼要地概括本次执行情况
   - 指出成功或失败的关键原因
   - 评估执行的完整性和有效性

4. **改进建议**
   - 基于分析结果提出针对性建议
   - 优化命令或流程的具体方案
   - 避免类似问题的预防措施

请用JSON格式输出，结构如下：
{{
  "key_nodes": [
    {{
      "time": "string (时间点)",
      "step": "string (执行步骤)",
      "description": "string (详细描述)",
      "significance": "high/medium/low (重要性)"
    }}
  ],
  "match_analysis": {{
    "user_intent": "string (用户原始需求)",
    "actual_result": "string (实际执行结果)",
    "match_score": int (0-100的匹配度评分)",
    "analysis": "string (详细分析)"
  }},
  "summary": {{
    "overall": "string (整体执行情况总结)",
    "success_factor": "string (成功原因或失败原因)",
    "execution_quality": "string (执行质量评估)"
  }},
  "suggestions": [
    {{
      "type": "optimization/error_prevention/best_practice",
      "suggestion": "string (建议内容)",
      "priority": "high/medium/low"
    }}
  ]
}}
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的运维分析专家，擅长分析单条日志并提供精准的优化建议。请始终以JSON格式输出分析结果。"},
            {"role": "user", "content": analysis_prompt}
        ]
        
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.3
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        with httpx.Client(timeout=60.0) as client:
            response = client.post(api_url, json=payload, headers=headers)
            
            if response.status_code != 200:
                current_app.logger.error(f"AI Single Log Analysis API error: {response.text}")
                return jsonify({
                    'success': False,
                    'message': f'AI 服务响应错误: {response.status_code}'
                }), 500
            
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                analysis_content = result['choices'][0]['message']['content'].strip()
                
                import json as json_mod
                import re
                
                code_pattern = r'```json?\n?(.*?)\n?```'
                match = re.search(code_pattern, analysis_content, re.DOTALL)
                if match:
                    analysis_content = match.group(1).strip()
                
                try:
                    analysis_data = json_mod.loads(analysis_content)
                    return jsonify({
                        'success': True,
                        'analysis': analysis_data,
                        'log_info': {
                            'id': task_log.id,
                            'status': task_log.status,
                            'created_at': task_log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                            'message': task_log.message
                        },
                        'task_info': {
                            'name': task.name,
                            'ai_prompt': task.ai_prompt
                        },
                        'raw_response': result['choices'][0]['message']['content']
                    })
                except json_mod.JSONDecodeError:
                    return jsonify({
                        'success': True,
                        'analysis_text': analysis_content,
                        'log_info': {
                            'id': task_log.id,
                            'status': task_log.status,
                            'created_at': task_log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                            'message': task_log.message
                        },
                        'task_info': {
                            'name': task.name,
                            'ai_prompt': task.ai_prompt
                        },
                        'raw_response': result['choices'][0]['message']['content']
                    })
            else:
                return jsonify({
                    'success': False,
                    'message': 'AI未能生成有效的分析结果'
                }), 500
                
    except httpx.TimeoutException:
        current_app.logger.error("AI Single Log Analysis API timeout")
        return jsonify({
            'success': False,
            'message': 'AI 分析请求超时，请稍后再试'
        }), 500
    except Exception as e:
        current_app.logger.error(f"AI single log analysis error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'AI 分析服务暂时不可用: {str(e)}'
        }), 500