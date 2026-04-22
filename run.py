from app import create_app, db
from app.models.user import User
from werkzeug.security import generate_password_hash

app = create_app()

@app.route('/')
def index():
    """首页"""
    from flask import render_template
    return render_template('index.html')

if __name__ == '__main__':
    # 创建数据库表 + 迁移
    with app.app_context():
        db.create_all()
        # ALTER migration: ai_analyses 加 server_id 列 + log_content 改 nullable
        try:
            from sqlalchemy import text
            db.session.execute(text('ALTER TABLE ai_analyses ADD COLUMN server_id INTEGER NULL'))
            db.session.execute(text('ALTER TABLE ai_analyses MODIFY COLUMN log_content TEXT NULL'))
            db.session.commit()
            print("Migration: ai_analyses updated (server_id added, log_content nullable)")
        except Exception as e:
            db.session.rollback()
            print(f"Migration note (may already exist): {e}")

    # 启动应用
    app.run(host='0.0.0.0', port=2080)