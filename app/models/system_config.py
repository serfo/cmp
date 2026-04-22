from app import db
from datetime import datetime
from enum import Enum

class ConfigCategory(Enum):
    """配置分类"""
    FLASK = 'flask'
    DATABASE = 'database'
    ZABBIX = 'zabbix'
    ANSIBLE = 'ansible'
    EMAIL = 'email'
    AI = 'ai'
    BACKUP = 'backup'
    LOGGING = 'logging'
    OTHER = 'other'

class SystemConfig(db.Model):
    """系统配置模型"""
    __tablename__ = 'system_configs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    value_type = db.Column(db.String(20), default='string')  # string, int, float, bool, json
    category = db.Column(db.String(20), default='other')
    description = db.Column(db.String(500), nullable=True)
    is_editable = db.Column(db.Boolean, default=True)
    is_sensitive = db.Column(db.Boolean, default=False)  # 敏感配置，值不可见
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<SystemConfig {self.key}>'
    
    def to_dict(self, include_sensitive=False):
        """转换为字典"""
        data = {
            'id': self.id,
            'key': self.key,
            'value': self.value if not self.is_sensitive or include_sensitive else '********',
            'value_type': self.value_type,
            'category': self.category,
            'description': self.description,
            'is_editable': self.is_editable,
            'is_sensitive': self.is_sensitive,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        return data
    
    @property
    def typed_value(self):
        """获取类型化值"""
        from ast import literal_eval
        import json
        
        if self.value is None:
            return None
            
        if self.value_type == 'int':
            return int(self.value)
        elif self.value_type == 'float':
            return float(self.value)
        elif self.value_type == 'bool':
            return self.value.lower() in ('true', '1', 'yes')
        elif self.value_type == 'json':
            try:
                return json.loads(self.value)
            except:
                return self.value
        else:
            return self.value
    
    @typed_value.setter
    def typed_value(self, value):
        """设置类型化值"""
        if value is None:
            self.value = None
        elif self.value_type == 'int':
            self.value = str(int(value))
        elif self.value_type == 'float':
            self.value = str(float(value))
        elif self.value_type == 'bool':
            self.value = 'true' if value else 'false'
        elif self.value_type == 'json':
            self.value = json.dumps(value, ensure_ascii=False)
        else:
            self.value = str(value)


class ConfigHistory(db.Model):
    """配置历史记录"""
    __tablename__ = 'config_history'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    config_id = db.Column(db.Integer, db.ForeignKey('system_configs.id'), nullable=True)
    config_key = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # create, update, delete, import
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    remark = db.Column(db.String(500), nullable=True)
    
    # 关系
    user = db.relationship('User', backref='config_changes')
    config = db.relationship('SystemConfig', backref='history')
    
    def __repr__(self):
        return f'<ConfigHistory {self.config_key} {self.action}>'
    
    def to_dict(self):
        """转换为字典"""
        change_summary = self._generate_change_summary()

        return {
            'id': self.id,
            'config_key': self.config_key,
            'action': self.action,
            'old_value': self._mask_value(self.old_value),
            'new_value': self._mask_value(self.new_value),
            'changed_by': self.changed_by,
            'changed_by_name': self.user.username if self.user else None,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'remark': self.remark,
            'change_summary': change_summary
        }

    def _mask_value(self, value, is_sensitive=False):
        """掩码敏感值"""
        if is_sensitive:
            return '******'
        if value is None:
            return None
        if len(str(value)) > 50:
            return str(value)[:50] + '...'
        return value

    def _generate_change_summary(self):
        """生成变更摘要"""
        is_sensitive = self._is_sensitive_config()

        if self.action == 'create':
            return f'创建配置项 {self.config_key}'
        elif self.action == 'delete':
            return f'删除配置项 {self.config_key}'
        elif self.action == 'import':
            return f'导入配置项 {self.config_key}'

        old_val = '******' if is_sensitive else (self.old_value if self.old_value else '(空)')
        new_val = '******' if is_sensitive else (self.new_value if self.new_value else '(空)')

        if old_val == new_val:
            return f'{self.config_key}: 未变更'

        return f'{self.config_key}: {old_val} → {new_val}'

    def _is_sensitive_config(self):
        """检查配置是否为敏感配置"""
        try:
            config = SystemConfig.query.filter_by(key=self.config_key).first()
            return config.is_sensitive if config else False
        except:
            return False
