from flask_mail import Mail, Message
from app import db
from app.models.email_log import EmailLog
import json

# 初始化邮件
mail = None

def init_mail(app):
    """初始化邮件服务"""
    global mail
    try:
        mail = Mail(app)
        print("邮件服务初始化成功")
    except Exception as e:
        mail = None
        print(f"邮件初始化失败: {e}")

def send_email(subject, recipients, body, html=None):
    """发送邮件"""
    import os
    from flask import current_app
    from app.config import Config

    # 获取 sender：优先从 app.config，再从 Config，最后从环境变量
    sender = (
        current_app.config.get('MAIL_DEFAULT_SENDER')
        or Config.get('MAIL_DEFAULT_SENDER')
        or os.environ.get('MAIL_DEFAULT_SENDER')
    )
    if not sender:
        sender = Config.get('MAIL_USERNAME') or os.environ.get('MAIL_USERNAME')

    # 记录邮件发送尝试
    email_log = EmailLog(
        subject=subject,
        recipients=json.dumps(recipients),
        body=body,
        html=html,
        success=False
    )

    if not mail:
        print("邮件服务未初始化")
        email_log.error_message = "邮件服务未初始化"
        db.session.add(email_log)
        db.session.commit()
        return False

    try:
        msg = Message(
            subject=subject,
            recipients=recipients,
            sender=sender
        )
        msg.body = body
        if html:
            msg.html = html

        mail.send(msg)
        email_log.success = True
        db.session.add(email_log)
        db.session.commit()
        return True
    except Exception as e:
        error_msg = str(e)
        print(f"邮件发送失败: {error_msg}")
        email_log.error_message = error_msg
        db.session.add(email_log)
        db.session.commit()
        return False

def send_alert_email(server, alert):
    """发送告警邮件"""
    subject = f"[{alert.severity.upper()}] 服务器告警 - {server.name} ({server.ip})"
    body = f"""告警信息：
服务器：{server.name} ({server.ip})
告警类型：{alert.alert_type}
告警级别：{alert.severity}
告警内容：{alert.message}
告警时间：{alert.created_at}
"""
    
    return send_email(subject, ['admin@supome.cn'], body)
