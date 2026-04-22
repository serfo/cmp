from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app import db
from app.models.system_config import SystemConfig, ConfigHistory, ConfigCategory
from werkzeug.security import generate_password_hash
import json
import datetime
import uuid
import os

config_bp = Blueprint('config', __name__, url_prefix='/config')

def detect_value_type(value_str):
    """自动检测值类型"""
    if value_str is None:
        return 'string'
    
    value_str = value_str.strip()
    
    # 布尔值
    if value_str.lower() in ('true', 'false', '1', '0', 'yes', 'no'):
        return 'bool'
    
    # 整数
    try:
        int(value_str)
        return 'int'
    except ValueError:
        pass
    
    # 浮点数
    try:
        float(value_str)
        return 'float'
    except ValueError:
        pass
    
    # JSON
    try:
        json.loads(value_str)
        return 'json'
    except json.JSONDecodeError:
        pass
    
    return 'string'

def parse_value(value_str, value_type):
    """解析值为指定类型"""
    if value_str is None:
        return None
    
    value_str = value_str.strip()
    
    if value_type == 'int':
        return int(value_str)
    elif value_type == 'float':
        return float(value_str)
    elif value_type == 'bool':
        return value_str.lower() in ('true', '1', 'yes')
    elif value_type == 'json':
        try:
            return json.loads(value_str)
        except:
            return value_str
    else:
        return value_str

@config_bp.route('/')
@login_required
def index():
    """配置管理首页"""
    # 获取所有配置
    configs = SystemConfig.query.order_by(SystemConfig.category, SystemConfig.key).all()
    
    # 按分类分组
    config_groups = {}
    for config in configs:
        if config.category not in config_groups:
            config_groups[config.category] = []
        config_groups[config.category].append(config)
    
    # 获取分类信息
    categories = []
    for cat in ConfigCategory:
        count = len(config_groups.get(cat.value, []))
        categories.append({
            'name': cat.value,
            'display_name': cat.value.title(),
            'count': count
        })
    
    # 计算总数
    total_count = len(configs)
    sensitive_count = sum(1 for c in configs if c.is_sensitive)
    
    return render_template('config/index.html',
                         configs=configs,
                         config_groups=config_groups,
                         categories=categories,
                         total_count=total_count,
                         sensitive_count=sensitive_count)

@config_bp.route('/api/list')
@login_required
def api_list():
    """API: 获取配置列表"""
    category = request.args.get('category', None)
    search = request.args.get('search', '')
    
    query = SystemConfig.query
    
    if category:
        query = query.filter_by(category=category)
    
    if search:
        search = f'%{search}%'
        query = query.filter(
            (SystemConfig.key.ilike(search)) |
            (SystemConfig.description.ilike(search))
        )
    
    configs = query.order_by(SystemConfig.category, SystemConfig.key).all()
    
    return jsonify({
        'success': True,
        'data': [config.to_dict(include_sensitive=False) for config in configs],
        'total': len(configs)
    })

@config_bp.route('/api/get/<config_key>')
@login_required
def api_get(config_key):
    """API: 获取单个配置"""
    config = SystemConfig.query.filter_by(key=config_key).first()
    
    if not config:
        return jsonify({
            'success': False,
            'message': '配置不存在'
        }), 404
    
    return jsonify({
        'success': True,
        'data': config.to_dict(include_sensitive=True)
    })

@config_bp.route('/api/update', methods=['POST'])
@login_required
def api_update():
    """API: 更新配置
    
    同时完成两项操作：
    1. 将更新后的配置值写入系统环境变量
    2. 将更新后的配置值持久化存储到数据库中
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': '无效的请求数据'
            }), 400
        
        config_key = data.get('key')
        new_value = data.get('value')
        remark = data.get('remark', '')
        
        if not config_key:
            return jsonify({
                'success': False,
                'message': '配置键不能为空'
            }), 400
        
        config = SystemConfig.query.filter_by(key=config_key).first()
        
        if not config:
            return jsonify({
                'success': False,
                'message': '配置不存在'
            }), 404
        
        if not config.is_editable:
            return jsonify({
                'success': False,
                'message': '该配置不可编辑'
            }), 403
        
        old_value = config.value
        
        if config.value_type == 'bool' and isinstance(new_value, bool):
            config.value = 'true' if new_value else 'false'
        elif config.value_type in ('int', 'float') and new_value is not None:
            config.value = str(new_value)
        else:
            config.value = new_value
        
        config.updated_at = datetime.datetime.utcnow()
        
        history = ConfigHistory(
            config_id=config.id,
            config_key=config.key,
            action='update',
            old_value=old_value,
            new_value=config.value,
            changed_by=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            remark=remark
        )
        db.session.add(history)
        
        db.session.commit()
        
        try:
            from app.config import Config as AppConfig
            AppConfig.set_env(config.key, config.value)
        except Exception as env_error:
            current_app.logger.warning(f"更新环境变量失败: {env_error}")
        
        return jsonify({
            'success': True,
            'message': '配置更新成功',
            'data': config.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'更新失败: {str(e)}'
        }), 500

@config_bp.route('/api/batch-update', methods=['POST'])
@login_required
def api_batch_update():
    """API: 批量更新配置"""
    try:
        data = request.get_json()
        
        if not data or 'configs' not in data:
            return jsonify({
                'success': False,
                'message': '无效的请求数据'
            }), 400
        
        configs_data = data['configs']
        remark = data.get('remark', '批量更新')
        
        updated_configs = []
        errors = []
        
        for item in configs_data:
            config_key = item.get('key')
            new_value = item.get('value')
            
            if not config_key:
                errors.append({'key': config_key, 'error': '配置键不能为空'})
                continue
            
            config = SystemConfig.query.filter_by(key=config_key).first()
            
            if not config:
                errors.append({'key': config_key, 'error': '配置不存在'})
                continue
            
            if not config.is_editable:
                errors.append({'key': config_key, 'error': '该配置不可编辑'})
                continue
            
            # 记录旧值
            old_value = config.value
            
            # 更新值
            if config.value_type == 'bool' and isinstance(new_value, bool):
                config.value = 'true' if new_value else 'false'
            elif config.value_type in ('int', 'float') and new_value is not None:
                config.value = str(new_value)
            else:
                config.value = new_value
            
            config.updated_at = datetime.datetime.utcnow()
            
            # 记录历史
            history = ConfigHistory(
                config_id=config.id,
                config_key=config.key,
                action='update',
                old_value=old_value,
                new_value=config.value,
                changed_by=current_user.id,
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent', '')[:500],
                remark=remark
            )
            db.session.add(history)

            try:
                from app.config import Config as AppConfig
                AppConfig.set_env(config.key, config.value)
            except Exception:
                pass

            updated_configs.append(config.key)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'成功更新 {len(updated_configs)} 个配置',
            'updated': updated_configs,
            'errors': errors
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量更新配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'批量更新失败: {str(e)}'
        }), 500

@config_bp.route('/api/create', methods=['POST'])
@login_required
def api_create():
    """API: 创建新配置"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': '无效的请求数据'
            }), 400
        
        key = data.get('key')
        value = data.get('value', '')
        value_type = data.get('value_type', detect_value_type(value))
        category = data.get('category', 'other')
        description = data.get('description', '')
        is_sensitive = data.get('is_sensitive', False)
        is_editable = data.get('is_editable', True)
        
        if not key:
            return jsonify({
                'success': False,
                'message': '配置键不能为空'
            }), 400
        
        # 检查键是否已存在
        if SystemConfig.query.filter_by(key=key).first():
            return jsonify({
                'success': False,
                'message': f'配置键 {key} 已存在'
            }), 400
        
        # 创建配置
        config = SystemConfig(
            key=key,
            value=str(value) if value is not None else '',
            value_type=value_type,
            category=category,
            description=description,
            is_sensitive=is_sensitive,
            is_editable=is_editable
        )
        
        db.session.add(config)
        
        # 记录历史
        history = ConfigHistory(
            config_id=config.id,
            config_key=config.key,
            action='create',
            old_value=None,
            new_value=config.value,
            changed_by=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            remark='创建新配置'
        )
        db.session.add(history)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '配置创建成功',
            'data': config.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"创建配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'创建失败: {str(e)}'
        }), 500

@config_bp.route('/api/delete/<config_key>', methods=['DELETE'])
@login_required
def api_delete(config_key):
    """API: 删除配置"""
    try:
        config = SystemConfig.query.filter_by(key=config_key).first()
        
        if not config:
            return jsonify({
                'success': False,
                'message': '配置不存在'
            }), 404
        
        if not config.is_editable:
            return jsonify({
                'success': False,
                'message': '该配置不可删除'
            }), 403
        
        # 记录旧值
        old_value = config.value
        
        # 记录历史
        history = ConfigHistory(
            config_id=config.id,
            config_key=config.key,
            action='delete',
            old_value=old_value,
            new_value=None,
            changed_by=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            remark='删除配置'
        )
        db.session.add(history)
        
        db.session.delete(config)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '配置删除成功'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }), 500

@config_bp.route('/api/export')
@login_required
def api_export():
    """API: 导出配置"""
    try:
        category = request.args.get('category', None)
        include_sensitive = request.args.get('include_sensitive', 'false').lower() == 'true'
        
        query = SystemConfig.query
        
        if category:
            query = query.filter_by(category=category)
        
        configs = query.order_by(SystemConfig.category, SystemConfig.key).all()
        
        export_data = {
            'export_time': datetime.datetime.utcnow().isoformat(),
            'version': '1.0',
            'configs': [config.to_dict(include_sensitive=include_sensitive) for config in configs]
        }
        
        # 生成文件名
        filename = f'cloud_platform_config_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        response = jsonify(export_data)
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Type'] = 'application/json'
        
        # 记录导出操作
        history = ConfigHistory(
            config_key='EXPORT',
            action='import',
            new_value=f'导出配置 {len(configs)} 条',
            changed_by=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            remark=f'导出配置，分类: {category or "全部"}'
        )
        db.session.add(history)
        db.session.commit()
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"导出配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'导出失败: {str(e)}'
        }), 500

@config_bp.route('/api/import', methods=['POST'])
@login_required
def api_import():
    """API: 导入配置"""
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': '请上传文件'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': '请选择文件'
            }), 400
        
        # 解析JSON
        try:
            data = json.load(file)
        except json.JSONDecodeError as e:
            return jsonify({
                'success': False,
                'message': f'JSON解析失败: {str(e)}'
            }), 400
        
        if 'configs' not in data:
            return jsonify({
                'success': False,
                'message': '无效的配置文件格式'
            }), 400
        
        # 导入配置
        imported = 0
        updated = 0
        errors = []
        
        for item in data['configs']:
            try:
                key = item.get('key')
                value = item.get('value', '')
                value_type = item.get('value_type', detect_value_type(value))
                category = item.get('category', 'other')
                description = item.get('description', '')
                is_sensitive = item.get('is_sensitive', False)
                is_editable = item.get('is_editable', True)
                
                if not key:
                    errors.append({'item': item, 'error': '配置键不能为空'})
                    continue
                
                # 检查是否存在
                existing = SystemConfig.query.filter_by(key=key).first()
                
                if existing:
                    # 更新现有配置
                    old_value = existing.value
                    existing.value = str(value) if value is not None else ''
                    existing.value_type = value_type
                    existing.category = category
                    existing.description = description
                    existing.is_sensitive = is_sensitive
                    existing.updated_at = datetime.datetime.utcnow()
                    
                    # 记录历史
                    history = ConfigHistory(
                        config_id=existing.id,
                        config_key=existing.key,
                        action='update',
                        old_value=old_value,
                        new_value=existing.value,
                        changed_by=current_user.id,
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent', '')[:500],
                        remark='通过导入更新'
                    )
                    db.session.add(history)
                    
                    updated += 1
                else:
                    # 创建新配置
                    config = SystemConfig(
                        key=key,
                        value=str(value) if value is not None else '',
                        value_type=value_type,
                        category=category,
                        description=description,
                        is_sensitive=is_sensitive,
                        is_editable=is_editable
                    )
                    db.session.add(config)
                    
                    # 记录历史
                    history = ConfigHistory(
                        config_id=config.id,
                        config_key=config.key,
                        action='create',
                        old_value=None,
                        new_value=config.value,
                        changed_by=current_user.id,
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent', '')[:500],
                        remark='通过导入创建'
                    )
                    db.session.add(history)
                    
                    imported += 1
                    
            except Exception as e:
                errors.append({'item': item.get('key', 'unknown'), 'error': str(e)})
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'导入完成: 新建 {imported} 条, 更新 {updated} 条',
            'imported': imported,
            'updated': updated,
            'errors': errors
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"导入配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'导入失败: {str(e)}'
        }), 500

@config_bp.route('/api/history')
@login_required
def api_history():
    """API: 获取配置历史"""
    try:
        config_key = request.args.get('config_key', None)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        query = ConfigHistory.query
        
        if config_key:
            query = query.filter_by(config_key=config_key)
        
        pagination = query.order_by(ConfigHistory.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [item.to_dict() for item in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        })
        
    except Exception as e:
        current_app.logger.error(f"获取配置历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取历史失败: {str(e)}'
        }), 500

@config_bp.route('/api/sync-to-system', methods=['POST'])
@login_required
def api_sync_to_system():
    """API: 从数据库同步配置到系统环境变量"""
    try:
        from app.config import Config as AppConfig
        
        # 从数据库同步配置到系统
        AppConfig.sync_from_database()
        
        configs = SystemConfig.query.all()
        
        # 记录同步操作到历史
        history = ConfigHistory(
            config_key='SYSTEM_SYNC',
            action='import',
            new_value=f'同步 {len(configs)} 条配置到系统',
            changed_by=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            remark='从数据库同步配置到系统环境变量'
        )
        db.session.add(history)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'配置同步完成，已同步 {len(configs)} 条配置到系统环境变量',
            'synced': len(configs)
        })
        
    except Exception as e:
        current_app.logger.error(f"同步配置到系统失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'同步失败: {str(e)}'
        }), 500
