from datetime import datetime
from app import db


class AIAnalysis(db.Model):
    """AI分析记录模型"""
    __tablename__ = 'ai_analyses'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    log_content = db.Column(db.Text, nullable=True)
    server_id = db.Column(db.Integer, db.ForeignKey('servers.id'), nullable=True)
    analysis_type = db.Column(db.String(50), nullable=False)
    conclusion = db.Column(db.Text, nullable=False)
    suggestions = db.Column(db.Text, nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    raw_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # 关系
    user = db.relationship('User', backref=db.backref('ai_analyses', lazy=True))
    server = db.relationship('Server', backref=db.backref('ai_analyses', lazy=True))

    def __repr__(self):
        return f'<AIAnalysis {self.id}>'