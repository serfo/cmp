from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from app import db
from app.models.user import User

def admin_required(f):
    """管理员权限装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# 创建蓝图
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)

            if user.role == 'user':
                scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
                host = request.headers.get('X-Forwarded-Host', request.host)
                user_dashboard_url = f'{scheme}://{host}/static/monitor/dashboard/index.html'
                return redirect(user_dashboard_url)
            else:
                return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'danger')

    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """用户登出"""
    logout_user()
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册"""
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        # 检查用户名是否已存在
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
            return redirect(url_for('auth.register'))
        
        # 检查邮箱是否已存在
        if User.query.filter_by(email=email).first():
            flash('邮箱已存在', 'danger')
            return redirect(url_for('auth.register'))
        
        # 创建新用户
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_password)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')

@auth_bp.route('/user_info')
@login_required
def user_info():
    """用户信息"""
    return render_template('auth/user_profile.html')

@auth_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """修改密码"""
    from flask import flash, redirect, url_for
    from flask_login import current_user
    from werkzeug.security import generate_password_hash, check_password_hash
    
    old_password = request.form['old_password']
    new_password = request.form['new_password']
    confirm_password = request.form['confirm_password']
    
    # 检查新密码和确认密码是否一致
    if new_password != confirm_password:
        flash('新密码和确认密码不一致', 'danger')
        return redirect(url_for('auth.user_info'))
    
    # 检查原密码是否正确
    if not check_password_hash(current_user.password, old_password):
        flash('原密码错误', 'danger')
        return redirect(url_for('auth.user_info'))
    
    # 更新密码
    current_user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
    db.session.commit()
    
    flash('密码修改成功', 'success')
    return redirect(url_for('auth.user_info'))