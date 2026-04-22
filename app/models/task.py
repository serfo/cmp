from datetime import datetime
from app import db

class Task(db.Model):
    """任务模型"""
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    task_type = db.Column(db.Enum('backup', 'deploy', 'monitor', 'command', 'other'), nullable=False)
    status = db.Column(db.Enum('pending', 'running', 'completed', 'failed'), nullable=False, default='pending')
    cron_expression = db.Column(db.String(50), nullable=True)
    command = db.Column(db.Text, nullable=False)
    ai_prompt = db.Column(db.Text, nullable=True)  # AI助手生成的原始用户输入
    target_servers = db.Column(db.Text, nullable=False)  # JSON格式
    timeout = db.Column(db.Integer, nullable=False, default=3600)  # 默认超时时间为3600秒
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_executed_at = db.Column(db.DateTime, nullable=True)
    next_executed_at = db.Column(db.DateTime, nullable=True)
    
    # 关系
    creator = db.relationship('User', backref='tasks', lazy=True)
    logs = db.relationship('TaskLog', backref='task', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Task {self.name} - {self.status}>'

class TaskLog(db.Model):
    """任务日志模型"""
    __tablename__ = 'task_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    status = db.Column(db.Enum('running', 'completed', 'failed'), nullable=False)
    message = db.Column(db.Text, nullable=True)
    output = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TaskLog {self.id} - {self.status}>'