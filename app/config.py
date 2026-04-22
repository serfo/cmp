import os
import json

class Config:
    """应用配置类

    配置管理：
    1. 初始配置从 config.json 读取（数据库连接等）
    2. 程序启动时从数据库加载所有配置到环境变量
    3. 所有代码通过环境变量获取配置
    4. 通过管理界面修改配置会实时更新环境变量和数据库
    """

    _config_cache = {}
    _initialized = False
    _db_initialized = False
    _db_config_loaded = False

    SQLALCHEMY_DATABASE_URI = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = 'your-secret-key-here'
    DEBUG = True

    AI_API_KEY = None
    AI_API_URL = None

    ZABBIX_URL = None
    ZABBIX_TOKEN = None

    _config_file_path = None

    @classmethod
    def get_config_file_path(cls):
        """获取配置文件路径"""
        if cls._config_file_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cls._config_file_path = os.path.join(base_dir, 'config.json')
        return cls._config_file_path

    @classmethod
    def load_config_file(cls):
        """从 config.json 加载初始配置"""
        config_path = cls.get_config_file_path()

        if not os.path.exists(config_path):
            print(f"[Config] 配置文件不存在: {config_path}")
            return {}

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config] 读取配置文件失败: {e}")
            return {}

    @classmethod
    def init_db_config(cls, app=None):
        """
        程序启动阶段调用，用于获取初始数据库连接信息
        """
        if cls._db_config_loaded:
            return
        #从 config.json 初始化数据库连接配置
        config_data = cls.load_config_file()
        db_config = config_data.get('database', {})
        host = db_config.get('host', '')
        port = db_config.get('port', 3306)
        username = db_config.get('username', '')
        password = db_config.get('password', '')
        name = db_config.get('name', '')

        uri = f'mysql+pymysql://{username}:{password}@{host}:{port}/{name}'
        cls.SQLALCHEMY_DATABASE_URI = uri

        os.environ['SQLALCHEMY_DATABASE_URI'] = uri
        cls._config_cache['SQLALCHEMY_DATABASE_URI'] = uri

        if app is not None:
            app.config['SQLALCHEMY_DATABASE_URI'] = uri

        cls._db_config_loaded = True
        print("[Config] 已加载数据库配置")

    @classmethod
    def init_app_config(cls, app=None):
        """从数据库动态加载所有配置属性并写入系统环境变量

        Args:
            app: Flask应用实例（可选，用于获取数据库连接）
        """
        if cls._initialized:
            return

        if cls._db_initialized:
            return

        try:
            if app is None:
                try:
                    from flask import current_app
                    app = current_app
                except RuntimeError:
                    print("[Config] 无应用上下文，跳过数据库配置加载")
                    cls._initialized = True
                    return

            from app import db
            from app.models.system_config import SystemConfig

            with app.app_context():
                configs = SystemConfig.query.all()

                for config in configs:
                    os.environ[config.key] = config.value if config.value else ''
                    cls._config_cache[config.key] = config.value

                    if hasattr(cls, config.key):
                        if config.key == 'DEBUG':
                            cls.DEBUG = config.value.lower() == 'true'
                        elif config.key == 'SECRET_KEY':
                            cls.SECRET_KEY = config.value or 'your-secret-key-here'
                        elif config.key == 'SQLALCHEMY_DATABASE_URI':
                            cls.SQLALCHEMY_DATABASE_URI = config.value or cls.SQLALCHEMY_DATABASE_URI
                        elif config.key in ['MAIL_PORT', 'BACKUP_INTERVAL', 'LOG_COLLECTION_INTERVAL', 'LOG_RETENTION_DAYS', 'LOG_COLLECTION_LIMIT']:
                            try:
                                setattr(cls, config.key, int(config.value) if config.value else getattr(cls, config.key))
                            except (ValueError, TypeError):
                                pass
                        elif config.key in ['MAIL_USE_SSL', 'MAIL_USE_TLS', 'SQLALCHEMY_TRACK_MODIFICATIONS']:
                            setattr(cls, config.key, config.value.lower() == 'true')
                        else:
                            setattr(cls, config.key, config.value or '')

                cls._initialized = True
                cls._db_initialized = True

                if configs:
                    print(f"[Config] 已从数据库加载 {len(configs)} 条配置到环境变量")
                else:
                    print("[Config] 数据库中没有配置项，使用默认配置")

        except Exception as e:
            print(f"[Config] 从数据库加载配置失败: {e}")
            print("[Config] 将使用环境变量和默认值")
            cls._initialized = True

    @classmethod
    def reload_from_db(cls, app=None):
        """从数据库重新加载配置"""
        cls._initialized = False
        cls._db_initialized = False
        cls._config_cache = {}
        cls.init_app_config(app)

    @classmethod
    def get(cls, key, default=None):
        """获取配置值

        优先级：1. 环境变量 2. 类属性 3. 数据库缓存 4. 默认值
        """
        if not cls._initialized:
            cls.init_app_config()

        if key in os.environ:
            return os.environ[key]

        if hasattr(cls, key):
            value = getattr(cls, key)
            if not callable(value):
                return value

        if key in cls._config_cache:
            return cls._config_cache[key]

        return default

    @classmethod
    def set_env(cls, key, value):
        """将配置值写入系统环境变量

        用于配置修改时同步更新环境变量
        """
        os.environ[key] = str(value) if value else ''
        cls._config_cache[key] = str(value) if value else ''

        if hasattr(cls, key):
            try:
                current_value = getattr(cls, key)
                if isinstance(current_value, bool):
                    setattr(cls, key, value.lower() == 'true')
                elif isinstance(current_value, int):
                    setattr(cls, key, int(value) if value else 0)
                else:
                    setattr(cls, key, value)
            except (ValueError, TypeError, AttributeError):
                pass

    @classmethod
    def get_int(cls, key, default=0):
        """获取整数配置"""
        try:
            return int(cls.get(key, default))
        except (ValueError, TypeError):
            return default

    @classmethod
    def get_bool(cls, key, default=False):
        """获取布尔配置"""
        value = cls.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes')

    @classmethod
    def get_float(cls, key, default=0.0):
        """获取浮点数配置"""
        try:
            return float(cls.get(key, default))
        except (ValueError, TypeError):
            return default

    @classmethod
    def sync_from_database(cls, app=None):
        """从数据库同步配置到系统环境变量"""
        cls.reload_from_db(app)