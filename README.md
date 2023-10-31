# MySQL Clone Backup

基于 MySQL 8.0 Clone 插件，实现的一套自动化备份系统。

### 1. 用途

* 实现自动化全量备份。
* 自动化 Binlog 增量备份。
* 过期备份自动清理。
* 备份信息 Dashboard 展示。
* 辅助基于时间点恢复数据。

### 2. 项目状态

正常维护，应用于公司部分线上环境。

* 已测试环境
  * Python 3.7
  * mysql  Ver 8.0.31 for Linux on x86_64 (MySQL Community Server - GPL)
  * CentOS Linux release 7.9.2009 (Core)

### 3. 备份系统架构

MySQL Clone Backup 是一款备份管理程序，依赖 MySQL 8.0 版本的 Clone 插件，对数据和日志文件进行备份，然后上传到 OSS 中，整个备份的过程以及备份信息都可以通过 Grafana 中的 Dashboard 查看，意味着它可以管理线下多套 MySQL 集群的备份。

![](https://github.com/COOH-791/mysql_clone_backup/blob/main/images/design.png)

#### 3.1 备份流程介绍

1. 首先进行环境检查，主要检查备份库是否安装 Clone 插件，元数据库中该实例是否存在。
2. 当确认环境具备备份条件后，程序将调用 Clone 备份。
3. 当 Clone 结束后，程序将对备份文件进行压缩。
4. 压缩完成后，程序会调用 OSS 接口将备份文件上传到 OSS 中。
5. 上传完成后，将清理本地的备份文件，如果失败则不清理，会修改任务状态说明失败原因。
6. 检查 OSS 上该备份是否存在，检查本地备份文件是否已经清理。
7. 检查完成后，备份任务状态修改为 Completed 任务结束。



