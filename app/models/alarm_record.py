from datetime import datetime
from app import db


class AlarmRecord(db.Model):
    """告警信息记录表 - 持久化Zabbix告警"""
    __tablename__ = 'alarm_record'

    alarm_id = db.Column(db.BigInteger, primary_key=True, nullable=False)
    alarm_title = db.Column(db.String(128), nullable=False)
    alarm_content = db.Column(db.Text, nullable=False)
    alarm_level = db.Column(db.SmallInteger, nullable=False)  # 0=info, 1=warning, 2=error, 3=critical
    resource_id = db.Column(db.String(64), nullable=False)  # Zabbix objectid/triggerid
    trigger_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.SmallInteger, nullable=False, default=0)  # 0=active, 1=resolved

    def __repr__(self):
        return f'<AlarmRecord {self.alarm_id} - {self.alarm_title}>'