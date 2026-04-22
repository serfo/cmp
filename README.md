<h4 id="rXMtj">部署服务</h4>

首先git clone本地

```plain
yum install git python-pip sshpass -y
```

```plain
git clone https://github.com/serfo/cmp.git
或者使用加速源
git clone https://gh-proxy.org/https://github.com/serfo/cmp.git
```

```plain
cd cmp
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

<h4 id="apvGf">Mysql</h4>

```plain
yum install mysql mysql-server -y
systemctl start mysqld
mysql_secure_installation
#输入完密码后，其他全部y回车
```

开启远程连接

```plain
mysql -uroot -pxxxxx
create database cmp;
use mysql;
update user set Host = '%' where Host = 'localhost' and User='root';
flush privileges;
```

创建数据库、导入sql

```plain
mysql -uroot -pxxxxx  cmp < cmp.sql
或者使用nvicat
```

<h4 id="qUbtw">zabbix</h4>

```plain
按照官网部署7.0.4
```

[下载Zabbix](https://www.zabbix.com/cn/download?zabbix=7.0&os_distribution=rocky_linux&os_version=9&components=server_frontend_agent&db=mysql&ws=nginx)

获取token

```plain
安装完成后默认账户Admin密码zabbix，在zabbix网页获得token
```

![](https://cdn.nlark.com/yuque/0/2026/png/25531544/1776825077456-399a3fe2-b80d-4695-8223-3aea4c61a4ad.png)

<h4 id="bLoLx">rsyslog</h4>

```plain
yum install rsyslog -y
mkdir /var/log/remote/ -p
```

配置文件设置

```plain
vi /etc/rsyslog.conf
```

```plain
# 使用系统默认配置（旧式语法，兼容保留）
$ModLoad imuxsock   # 本地系统日志（通过 /dev/log）
$ModLoad imjournal  # 从 systemd journal 读取
$ModLoad imklog     # 内核日志（/proc/kmsg）

# 加载远程接收模块（使用新式语法）
module(load="imtcp")
module(load="imudp")

# 配置监听端口（TCP/UDP 5140）
input(type="imtcp" port="5140")
input(type="imudp" port="5140")

# 全局设置
$WorkDirectory /var/lib/rsyslog
$ActionFileDefaultTemplate RSYSLOG_TraditionalFileFormat

# 包含子配置目录（保持默认）
$IncludeConfig /etc/rsyslog.d/*.conf

# 定义远程日志存储模板：按日期和 IP 分目录
$template RemoteLogs,"/var/log/remote/%$YEAR%-%$MONTH%-%$DAY%/%FROMHOST-IP%.log"

# 处理远程日志：排除本机（127.0.0.1），写入指定路径并停止后续处理
if $fromhost-ip != "127.0.0.1" then {
    action(type="omfile" dynaFile="RemoteLogs")
    stop
}

# ========== 本地日志规则（保持不变） ==========
*.info;mail.none;authpriv.none;cron.none    /var/log/messages
authpriv.*                                  /var/log/secure
mail.*                                      -/var/log/maillog
cron.*                                      /var/log/cron
*.emerg                                     :omusrmsg:*
uucp,news.crit                              /var/log/spooler
local7.*                                    /var/log/boot.log

```

<h3 id="ly5zt">配置代码</h3>

然后修改config.json的数据库配置，例如：

```plain
{
    "database": {
        "host": "localhost",
        "port": 3306,
        "username": "root",
        "password": "xxxxxxxxx",
        "name": "cmp"
    }
}
```

直接启动，或者写入system

```plain
python3 run.py
```

<h3 id="E2Nvo">初始化</h3>

关闭防火墙

```plain
systemctl stop firewalld
```

在网页ip:2080  --> 输入账户admin密码123456  -->  系统配置配置zabbix api --> 重启程序



