# MySQL Clone 基于时间点恢复

## 前言

通过 mysql_clone_backup 可以将所有全量备份和 Binlog 备份打包上传至 OSS，当发生灾难需要恢复的时候，是怎么的操作流程呢？本篇文章将介绍如何手动操作 PITR 恢复，未来会将这部分工作自动化。

## 1. 恢复目标

从 OSS 中下载全量备份及 Binlog 备份，将 Clone 备份的全量备份恢复与增量恢复，将数据恢复到一个新实例。下面是我们需要恢复的文件：

* bak_106_20231110020001.tar.gz：备份的时间点是 2023-11-10 02:01:10

* log_106_mysql-bin.000097：备份的时间点是 2023-11-10 01:49:19 ～ 2023-11-10 02:02:54

* log_106_mysql-bin.000098：备份的时间点是 2023-11-10 02:02:54 ～ 2023-11-10 02:18:58

* log_106_mysql-bin.000099：备份的时间点是 2023-11-10 02:18:58 ～ 2023-11-10 02:35:00

* log_106_mysql-bin.000100：备份的时间点是 2023-11-10 02:35:00 ～ 2023-11-10 02:51:10

* log_106_mysql-bin.000101：备份的时间点是 2023-11-10 02:51:10 ～ 2023-11-10 03:06:57

* log_106_mysql-bin.000102：备份的时间点是 2023-11-10 03:06:57 ～ 2023-11-10 03:23:00

* log_106_mysql-bin.000103：备份的时间点是 2023-11-10 03:23:00 ～ 2023-11-10 03:36:27

* log_106_mysql-bin.000104：备份的时间点是 2023-11-10 03:36:27 ～ 2023-11-10 03:48:46

## 2. 全量数据恢复

首先，需要把备份文件全部下载到一个新的 MySQL 环境下，关闭 MySQL 服务。

> 一定是全新的环境，清空 binlog 和 relary log 等日志文件。

然后，清理掉数据目录：

```sh
rm -rf /data/mysql_80/data/
```

加压缩备份文件：

```sh
tar -zxvf bak_106_20231110020001.tar.gz
```

移动到原本的数据目录：

```sh
mv bak_106_20231110020001 /data/mysql_80/data
```

修改文件属组：

```sh
chown -R mysql:mysql /data/mysql_80/
```

启动数据库，当数据库启动成功，表示 clone 全量备份已恢复完成。

## 3. 增量备份恢复

MySQL 8.0 版本默认开启 GTID 及多线程复制，所以呢，恢复的时候我们使用伪装 relay log 的方式进行增量日志的恢复。

从备份集的时间点，可以看出 log_106_mysql-bin.000097 Binlog 有部分 Event 要早于备份集的时间点，这块不用担心，因为 Clone 默认会记录源库的 GTID 位点信息，已经执行过的 GTID Event 会自动跳过。

首先，需要先执行如下：

```sql
reset replica all;
```

然后，进行 relay log 注册，就是将 Binlog 日志，按照 relay 格式写入到 relay log index 文件中，并拷贝到对应的目录下。

```sh
cat mysql-relay.index 

# 输出：
/data/mysql_80/logs/mysql-relay.000001
/data/mysql_80/logs/mysql-relay.000002
/data/mysql_80/logs/mysql-relay.000003
/data/mysql_80/logs/mysql-relay.000004
/data/mysql_80/logs/mysql-relay.000005
/data/mysql_80/logs/mysql-relay.000006
/data/mysql_80/logs/mysql-relay.000007
/data/mysql_80/logs/mysql-relay.000008
```

```sh
>> pwd
/data/mysql_80/logs

>> ll mysql-relay.*
-rw-r--r-- 1 root root 450497168 11月 10 14:32 mysql-relay.000001
-rw-r--r-- 1 root root 524323597 11月 10 14:33 mysql-relay.000002
-rw-r--r-- 1 root root 524736739 11月 10 14:33 mysql-relay.000003
-rw-r--r-- 1 root root 524827311 11月 10 14:33 mysql-relay.000004
-rw-r--r-- 1 root root 524311167 11月 10 14:33 mysql-relay.000005
-rw-r--r-- 1 root root 524298030 11月 10 14:33 mysql-relay.000006
-rw-r--r-- 1 root root 524829686 11月 10 14:33 mysql-relay.000007
-rw-r--r-- 1 root root 524839319 11月 10 14:33 mysql-relay.000008
-rw-r----- 1 root root       312 11月 10 14:33 mysql-relay.index
```

```sh
# 修改文件属组
chown -R mysql:mysql ./*
```

至此，已经将 relary log 注册完成。接下来需要创建复制通道：

```sql
change master to 
    master_host='localhost',
    master_port=3306,
    MASTER_AUTO_POSITION=0,
    RELAY_LOG_FILE='mysql-relay.000001',
    RELAY_LOG_POS=4;
```

开启 SQL 线程：

```sql
start replica sql_thread;
```

可以使用下方命令查看 SQL 线程应用情况：

```sql
show replica status\G
```

```sql
Relay_Log_File: mysql-relay.000009
Relay_Log_Pos: 4
Retrieved_Gtid_Set: e6a89772-568e-11ee-b973-0050569cd7aa:69-20170887
Executed_Gtid_Set: e6a89772-568e-11ee-b973-0050569cd7aa:1-20170887
```

注册了 8 个 Relary log 数据库回放完成后，会自动清理掉这些日志，然后新建一个新的 relary log 所以当看到 `Relay_Log_File = mysql-relay.000009` 的时候，且 Replica_SQL_Running_State 无任何报错时，就表示增量日志已经恢复完成。

