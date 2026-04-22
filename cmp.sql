SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for ai_analyses
-- ----------------------------
DROP TABLE IF EXISTS `ai_analyses`;
CREATE TABLE `ai_analyses`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `log_content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `analysis_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `conclusion` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `suggestions` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `confidence` float NOT NULL,
  `raw_response` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `server_id` int NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `user_id`(`user_id` ASC) USING BTREE,
  CONSTRAINT `ai_analyses_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 99 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = 'ai分析记录表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of ai_analyses
-- ----------------------------

-- ----------------------------
-- Table structure for alarm_record
-- ----------------------------
DROP TABLE IF EXISTS `alarm_record`;
CREATE TABLE `alarm_record`  (
  `alarm_id` bigint NOT NULL COMMENT '告警ID',
  `alarm_title` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '告警标题',
  `alarm_content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '告警详情',
  `alarm_level` tinyint NOT NULL COMMENT '告警级别',
  `resource_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '关联资源ID',
  `trigger_time` datetime NOT NULL COMMENT '触发时间',
  `status` tinyint NOT NULL COMMENT '告警状态',
  PRIMARY KEY (`alarm_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_bin COMMENT = '告警信息记录表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of alarm_record
-- ----------------------------

-- ----------------------------
-- Table structure for config_history
-- ----------------------------
DROP TABLE IF EXISTS `config_history`;
CREATE TABLE `config_history`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `config_id` int NULL DEFAULT NULL,
  `config_key` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `action` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `old_value` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  `new_value` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  `changed_by` int NULL DEFAULT NULL,
  `ip_address` varchar(45) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  `user_agent` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  `created_at` datetime NULL DEFAULT NULL,
  `remark` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `config_id`(`config_id` ASC) USING BTREE,
  INDEX `changed_by`(`changed_by` ASC) USING BTREE,
  CONSTRAINT `config_history_ibfk_1` FOREIGN KEY (`config_id`) REFERENCES `system_configs` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `config_history_ibfk_2` FOREIGN KEY (`changed_by`) REFERENCES `users` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 49 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_bin COMMENT = '系统配置修改记录' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of config_history
-- ----------------------------

-- ----------------------------
-- Table structure for email_logs
-- ----------------------------
DROP TABLE IF EXISTS `email_logs`;
CREATE TABLE `email_logs`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `subject` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `recipients` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `body` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `html` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `success` tinyint(1) NOT NULL,
  `error_message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 79 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '邮件发送记录表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of email_logs
-- ----------------------------

-- ----------------------------
-- Table structure for servers
-- ----------------------------
DROP TABLE IF EXISTS `servers`;
CREATE TABLE `servers`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `port` int NOT NULL DEFAULT 22,
  `username` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `os` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `cpu` int NULL DEFAULT NULL,
  `memory` int NULL DEFAULT NULL,
  `disk` int NULL DEFAULT NULL,
  `status` enum('online','offline','warning','error') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'offline',
  `zabbix_hostid` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `ip`(`ip` ASC) USING BTREE,
  INDEX `idx_servers_ip`(`ip` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 43 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '服务器表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of servers
-- ----------------------------

-- ----------------------------
-- Table structure for system_configs
-- ----------------------------
DROP TABLE IF EXISTS `system_configs`;
CREATE TABLE `system_configs`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `key` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `value` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  `value_type` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `category` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `description` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  `is_editable` tinyint(1) NOT NULL,
  `is_sensitive` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `created_by` int NULL DEFAULT NULL,
  `updated_by` int NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `ix_system_configs_key`(`key` ASC) USING BTREE,
  INDEX `created_by`(`created_by` ASC) USING BTREE,
  INDEX `updated_by`(`updated_by` ASC) USING BTREE,
  INDEX `idx_config_key`(`key` ASC) USING BTREE,
  INDEX `ix_system_configs_category`(`category` ASC) USING BTREE,
  INDEX `idx_config_category`(`category` ASC) USING BTREE,
  CONSTRAINT `system_configs_ibfk_1` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `system_configs_ibfk_2` FOREIGN KEY (`updated_by`) REFERENCES `users` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 25 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_bin COMMENT = '系统配置表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of system_configs
-- ----------------------------
INSERT INTO `system_configs` VALUES (1, 'AI_API_KEY', '', 'string', 'ai', 'AI API密钥', 1, 1, '2026-01-31 12:05:37', '2026-01-31 12:05:37', NULL, NULL);
INSERT INTO `system_configs` VALUES (2, 'AI_API_URL', 'https://api.deepseek.com/v1/chat/completions', 'string', 'ai', 'AI API地址', 1, 0, '2026-01-31 12:05:38', '2026-01-31 12:05:38', NULL, NULL);
INSERT INTO `system_configs` VALUES (4, 'BACKUP_DIR', '/tmp/test_backup', 'string', 'backup', '备份目录', 1, 0, '2026-01-31 12:05:38', '2026-04-12 10:49:48', NULL, NULL);
INSERT INTO `system_configs` VALUES (5, 'BACKUP_INTERVAL', '600', 'int', 'backup', '备份间隔(秒)', 1, 0, '2026-01-31 12:05:39', '2026-04-12 04:26:31', NULL, NULL);
INSERT INTO `system_configs` VALUES (6, 'DEBUG', 'true', 'bool', 'flask', '调试模式', 1, 0, '2026-01-31 12:05:39', '2026-01-31 12:05:39', NULL, NULL);
INSERT INTO `system_configs` VALUES (7, 'LOGIN_VIEW', 'auth.login', 'string', 'flask', '登录视图', 1, 0, '2026-01-31 12:05:40', '2026-01-31 12:05:40', NULL, NULL);
INSERT INTO `system_configs` VALUES (12, 'MAIL_DEFAULT_SENDER', '', 'string', 'email', '默认发件人', 1, 0, '2026-01-31 12:05:42', '2026-01-31 12:05:42', NULL, NULL);
INSERT INTO `system_configs` VALUES (13, 'MAIL_PASSWORD', '', 'string', 'email', '邮件密码', 1, 1, '2026-01-31 12:05:42', '2026-04-21 01:30:04', NULL, NULL);
INSERT INTO `system_configs` VALUES (14, 'MAIL_PORT', '', 'int', 'email', '邮件端口', 1, 0, '2026-01-31 12:05:42', '2026-01-31 12:05:42', NULL, NULL);
INSERT INTO `system_configs` VALUES (15, 'MAIL_SERVER', '', 'string', 'email', '邮件服务器', 1, 0, '2026-01-31 12:05:43', '2026-01-31 12:05:43', NULL, NULL);
INSERT INTO `system_configs` VALUES (16, 'MAIL_USERNAME', '', 'string', 'email', '邮件用户名', 1, 1, '2026-01-31 12:05:44', '2026-04-12 04:28:01', NULL, NULL);
INSERT INTO `system_configs` VALUES (17, 'MAIL_USE_SSL', 'true', 'bool', 'email', '使用SSL', 1, 0, '2026-01-31 12:05:44', '2026-01-31 12:05:44', NULL, NULL);
INSERT INTO `system_configs` VALUES (18, 'MAIL_USE_TLS', 'false', 'bool', 'email', '使用TLS', 1, 0, '2026-01-31 12:05:44', '2026-01-31 12:05:44', NULL, NULL);
INSERT INTO `system_configs` VALUES (19, 'SECRET_KEY', 'your-secret-key-here', 'string', 'flask', 'Flask密钥', 0, 1, '2026-01-31 12:05:45', '2026-01-31 12:05:45', NULL, NULL);
INSERT INTO `system_configs` VALUES (21, 'SQLALCHEMY_TRACK_MODIFICATIONS', 'false', 'bool', 'database', '跟踪修改', 1, 0, '2026-01-31 12:05:46', '2026-01-31 12:05:46', NULL, NULL);
INSERT INTO `system_configs` VALUES (22, 'ZABBIX_TOKEN', '', 'string', 'zabbix', 'Zabbix令牌', 1, 1, '2026-01-31 12:05:46', '2026-02-07 14:45:08', NULL, NULL);
INSERT INTO `system_configs` VALUES (23, 'ZABBIX_URL', 'http://xxx:8080/api_jsonrpc.php', 'string', 'zabbix', 'Zabbix地址', 1, 0, '2026-01-31 12:05:46', '2026-02-07 14:29:20', NULL, NULL);

-- ----------------------------
-- Table structure for task_logs
-- ----------------------------
DROP TABLE IF EXISTS `task_logs`;
CREATE TABLE `task_logs`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `task_id` int NOT NULL,
  `status` enum('running','completed','failed') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `output` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `task_id`(`task_id` ASC) USING BTREE,
  CONSTRAINT `task_logs_ibfk_1` FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 223 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '任务日志表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of task_logs
-- ----------------------------

-- ----------------------------
-- Table structure for tasks
-- ----------------------------
DROP TABLE IF EXISTS `tasks`;
CREATE TABLE `tasks`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `task_type` enum('backup','deploy','monitor','command','other') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` enum('pending','running','completed','failed') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `cron_expression` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `command` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `ai_prompt` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL COMMENT 'AI助手生成的原始用户输入',
  `target_servers` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by` int NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `last_executed_at` datetime NULL DEFAULT NULL,
  `next_executed_at` datetime NULL DEFAULT NULL,
  `timeout` int NOT NULL DEFAULT 3600,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `created_by`(`created_by` ASC) USING BTREE,
  CONSTRAINT `tasks_ibfk_1` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 92 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '任务表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of tasks
-- ----------------------------

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` enum('admin','user') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'user',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `ai_quota` int NOT NULL DEFAULT 100,
  `ai_used` int NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `username`(`username` ASC) USING BTREE,
  UNIQUE INDEX `email`(`email` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 7 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '用户表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of users
-- ----------------------------
INSERT INTO `users` VALUES (6, 'admin', 'pbkdf2:sha256:1000000$de8VhZCjySgr7pLb$ac104ccb0e2cb61315cb3a78943ef822ac97f2c6834546e0bcc4f3bda5243f9a', '123@123.com', 'admin', '2026-04-22 02:36:49', '2026-04-22 10:37:36', 100, 0);

SET FOREIGN_KEY_CHECKS = 1;
