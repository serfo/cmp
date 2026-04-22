from datetime import datetime
from app import db

class EmailLog(db.Model):
    """邮件发送记录模型"""
    __tablename__ = 'email_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subject = db.Column(db.String(255), nullable=False)
    recipients = db.Column(db.Text, nullable=False)  # JSON格式存储收件人列表
    body = db.Column(db.Text, nullable=False)
    html = db.Column(db.Text, nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EmailLog {self.id} - {"成功" if self.success else "失败"}>'
