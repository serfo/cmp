from datetime import datetime
from app import db

class Server(db.Model):
    """服务器模型"""
    __tablename__ = 'servers'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    ip = db.Column(db.String(50), unique=True, nullable=False)
    port = db.Column(db.Integer, nullable=False, default=22)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    os = db.Column(db.String(50), nullable=True)
    cpu = db.Column(db.Integer, nullable=True)
    memory = db.Column(db.Integer, nullable=True)
    disk = db.Column(db.Integer, nullable=True)
    status = db.Column(db.Enum('online', 'offline', 'warning', 'error'), nullable=False, default='offline')
    zabbix_hostid = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Server {self.name} ({self.ip})>'