# MySQL Clone Plugin Details

## 前言

克隆插件（Clone Plugin）是 MySQL 8.0.17 引入的一个重大特性，可以从本地或者远程克隆数据。

如果在 8.0.17 之前想要给 MySQL 复制拓扑中添加一个新节点，只支持 Binlog 一种恢复方式，如果新节点所需要的 Binlog 在集群中不存在，就只能先借助备份工具进行全量备份恢复，再配置增量同步。这种方式虽然能达到添加新节点的目的，但总归是需要借助外部工具，相对来说是有一定的使用门槛和工作量。

Clone 插件支持本地克隆和远程克隆，可以很方便的帮助我们添加一个新的节点，也可以作为 Innodb 引擎的物理备份工具。

## 1. 克隆插件安装
可以在配置文件中配置：

```ini
[mysqld]
plugin-load-add=mysql_clone.so
```
或者在 MySQL 中执行：

```sql
install plugin clone soname 'mysql_clone.so';
```
可通过下方 SQL 查询 Clone 插件状态：

```sql
-- SQL：
SELECT PLUGIN_NAME, PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME = 'clone';

-- 输出：
+-------------+---------------+
| PLUGIN_NAME | PLUGIN_STATUS |
+-------------+---------------+
| clone       | ACTIVE        |
+-------------+---------------+
```
如果想要卸载或者重新加载 Clone 插件，可使用下方命令：

```sql
uninstall plugin clone;
```
## 2. 克隆插件的使用
克隆插件支持本地克隆和远程克隆，接下来我们分别介绍使用方法。
### 2.1 本地克隆
本地 Clone 的原理可参考下图，它可以将本地的数据文件拷贝到服务器的一个目录中，本地 Clone 只能在实例本地发起。

![](https://github.com/COOH-791/mysql_clone_backup/blob/main/images/clone-local.png)

本地 Clone 命令的语法如下：

```sql
CLONE LOCAL DATA DIRECTORY [=] 'clone_dir';
```
只需指点克隆路径即可，下面将进行一个具体演示。

**a. 创建克隆专用的用户**
```sql
-- 创建用户
create user backup_clone@'127.0.0.1' identified by 'YouPassword';

-- 授予本地克隆权限
GRANT BACKUP_ADMIN ON *.* TO backup_clone@'127.0.0.1';

-- 授予克隆信息查看权限
GRANT SELECT ON performance_schema.clone_status TO backup_clone@'127.0.0.1';
```

**b. 创建克隆目录**

```bash
mkdir /data/clone_bak
chown -R mysql:mysql /data/clone_bak
```
**c. 执行克隆命令**

```sql
CLONE LOCAL DATA DIRECTORY = '/data/clone_bak/20231106';
```
这里的 `/data/clone_bak/20231106` 是克隆目录，它需要满足 3 个要求：
* 克咯目录必须是绝对路径。
* 其中 /data/clone_bak 必须存在，且 MySQL 对其有写权限。
* 最后一级目录 20231106 不能存在。

**d. 查看克隆目录的内容**

```bash
ll /data/clone_bak/20231106

# 输出：
总用量 570376
drwxr-x--- 2 mysql mysql        89 11月  6 11:27 #clone
-rw-r----- 1 mysql mysql      4373 11月  6 11:27 ib_buffer_pool
-rw-r----- 1 mysql mysql 524288000 11月  6 11:27 ibdata1
drwxr-x--- 2 mysql mysql        23 11月  6 11:27 #innodb_redo
drwxr-x--- 2 mysql mysql         6 11月  6 11:27 mysql
-rw-r----- 1 mysql mysql  26214400 11月  6 11:27 mysql.ibd
drwxr-x--- 2 mysql mysql        28 11月  6 11:27 sys
-rw-r----- 1 mysql mysql  16777216 11月  6 11:27 undo_001
-rw-r----- 1 mysql mysql  16777216 11月  6 11:27 undo_002
```
可以直接基于这些数据文件启动 MySQL 实例，相较于 Xtrabackup 克隆插件无须 Prepare 阶段。
### 2.2 远程克隆
远程克隆的原理可参考下图，克隆角色分为接收者 (recipient) 与捐赠者 (donor)，默认情况下使用远程克隆会删除 “接收者” 数据目录中的数据，替换为 “捐赠者” 的克隆数据。当然也可以选择将克隆的数据分配到 “接收者” 的其它目录，避免删除 “接收者” 现有的数据。

![](https://github.com/COOH-791/mysql_clone_backup/blob/main/images/clone-remote.png)

远程克隆的语法如下：

```sql
CLONE INSTANCE FROM 'user'@'host':port
IDENTIFIED BY 'password'
[DATA DIRECTORY [=] 'clone_dir']
[REQUIRE [NO] SSL];
```
参数含义介绍：
* user：登陆捐赠者实例的用户名。
* host：捐赠者实例的主机名或 IP。
* port：捐赠者实例的端口。
* password：捐赠者实例的密码。
* clone_dir：不指定 clone_dir 时，会清空接收者实例的 datadir 目录，并将数据放到 datadir 指定路径。如果指定了 data directory，则该路径需要不存在，mysql 服务需要有目录权限。
* REQUIRE [NO] SSL：指定传输数据是是否使用加密协议。

下面将进行一个具体演示，操作环境介绍：
| 主机          | 版本   | 角色   | Clone Pluge |
| ------------- | ------ | ------ | ----------- |
| 172.16.104.57 | 8.0.32 | 捐赠者 | ACTIVE      |
| 172.16.104.56 | 8.0.32 | 接收者 | ACTIVE      |

**a. 在捐赠者实例上创建相关账号并授权**

```sql
CREATE USER 'donor_user'@'%' IDENTIFIED BY 'password';
GRANT BACKUP_ADMIN on *.* to 'donor_user'@'%';
```
**b. 在接收者实例上创建账号并授权**

```bash
CREATE USER 'recipient_user'@'%' IDENTIFIED BY 'password';
GRANT CLONE_ADMIN on *.* to 'recipient_user'@'%';
```
这里 CLONE_ADMIN 权限，隐含有 BACKUP_ADMIN 和 SHUTDOWN 重启实例权限。

**c. 在接收者实例上设置捐赠者白名单**

```sql
SET GLOBAL clone_valid_donor_list = '172.16.104.57:3306';
```
接收者只能克隆白名单列表内捐赠者的数据，如果有多个实例使用逗号分隔。

**d. 在接收者实例上发起远程克隆**

```sql
CLONE INSTANCE FROM 'donor_user'@'172.16.104.57':3306 IDENTIFIED BY 'password';
```
获取备份锁（backup lock）备份锁与 DDL 互斥。捐赠者与接收者两个节点的备份锁都要获取。远程克隆结束后，会重启接收者节点。如果克隆命令指定克隆目录 `DATA DIRECTORY` 则不会重启。

## 3. 克隆任务监控
MySQL 提供两张表，监控克隆任务及查看任务状态。分别是 performance_schema 下的 clone_status 和 clone_progress 表。

首先看看 clone_status 表，该表记录了克隆操作的状态信息。

```sql
root@mysql 15:07:  [(none)]>select * from performance_schema.clone_status\G
*************************** 1. row ***************************
             ID: 1
            PID: 0
          STATE: Completed
     BEGIN_TIME: 2023-11-06 14:57:26.647
       END_TIME: 2023-11-06 14:57:39.406
         SOURCE: 172.16.104.57:3306
    DESTINATION: LOCAL INSTANCE
       ERROR_NO: 0
  ERROR_MESSAGE: 
    BINLOG_FILE: mysql-bin.000001
BINLOG_POSITION: 3185
  GTID_EXECUTED: 1b03028c-76f7-11ee-ac46-faa7cd9c6a00:1-4,
eccc6b43-b0fc-11ed-8e74-fa0e3cc40b00:1-3
```
其中各字段含义如下：
* ID：任务 ID。
* PID：对应 show processlist 中的 ID，如果要终止克隆任务，可以执行 KILL QUERY processlist_id。
* STATE：克隆操作的状态，包括 Not Started（尚未开始）In Progress（进行中）Completed（成功）Failed（失败）。
* BEGIN_TIME：克隆任务开始时间。
* END_TIME：克隆任务结束时间。
* SOURCE：Donor 实例的地址。
* DESTINATION：克隆目录。
* BINLOG_FILE & BINLOG_POSITION & GTID_EXECUTED：克隆操作对应的一致性位点信息，可利用这些信息搭建从库。
* ERROR_MESSAGE：如果任务失败，该字段会显示报错内容。

接下来查看 clone_progress 表，该表记录克隆任务的进度信息。

```bash
select * from performance_schema.clone_progress;
```
| ID   | STAGE     | STATE     | BEGIN\_TIME                | END\_TIME                  | THREADS | ESTIMATE  | DATA      | NETWORK   | DATA\_SPEED | NETWORK\_SPEED |
| :--- | :-------- | :-------- | :------------------------- | :------------------------- | :------ | :-------- | :-------- | :-------- | :---------- | :------------- |
| 1    | DROP DATA | Completed | 2023-11-06 14:57:26.673385 | 2023-11-06 14:57:26.891470 | 1       | 0         | 0         | 0         | 0           | 0              |
| 1    | FILE COPY | Completed | 2023-11-06 14:57:26.891645 | 2023-11-06 14:57:31.875850 | 1       | 583241456 | 583241456 | 583281243 | 0           | 0              |
| 1    | PAGE COPY | Completed | 2023-11-06 14:57:31.876114 | 2023-11-06 14:57:31.882372 | 1       | 0         | 0         | 99        | 0           | 0              |
| 1    | REDO COPY | Completed | 2023-11-06 14:57:31.882550 | 2023-11-06 14:57:31.885697 | 1       | 2560      | 2560      | 2901      | 0           | 0              |
| 1    | FILE SYNC | Completed | 2023-11-06 14:57:31.885818 | 2023-11-06 14:57:32.775465 | 1       | 0         | 0         | 0         | 0           | 0              |
| 1    | RESTART   | Completed | 2023-11-06 14:57:32.775465 | 2023-11-06 14:57:37.769087 | 0       | 0         | 0         | 0         | 0           | 0              |
| 1    | RECOVERY  | Completed | 2023-11-06 14:57:37.769087 | 2023-11-06 14:57:39.405806 | 0       | 0         | 0         | 0         | 0           | 0              |


其中各字段含义如下：
* STAGE：一个克隆任务有 7 个阶段，分别是 DROP DATA、FILE COPY、PAGE COPY、REDO COPY、FILE SYNC、RESTART、RESTART 当前阶段结束后才会开始进入下一阶段。
* STATE：当前阶段状态。
* BEGIN_TIME & END_TIME：当前阶段的开始时间和结束时间。
* THREADS：当前阶段使用的并发线程数。
* ESTIMATE：预估数据量。
* DATA：已拷贝的数据量。
* NETWORK：通过网络传输的数据量。
* DATA_SPEED：当前任务拷贝的速率。
* NETWORK_SPEED：当前任务网络传输的速率。

## 4. 克隆插件实现
![在这里插入图片描述](https://img-blog.csdnimg.cn/08645cb7127345618946dda851e88da4.png)
>参考来源：[YunChe MySQL 实战课程 clone 插件原理
>](https://yunche.pro/blog/?id=684)

克隆插件可以细分 5 个阶段：

**a. Init 阶段**

初始化一个克隆对象。

**b. File Copy**

拷贝数据文件。在拷贝之前，会将当前的检查点 LSN 记为 CLONE START LSN，同时启动 Page Tracking。

Page Tracking 会跟踪 CLONE START LSN 之后发生修改的页，记录这些页面的元数据信息 tablespace ID 和 page ID。数据文件拷贝结束后，会将当前检查点的 LSN 记为 CLONE FILE END LSN。

File Copy 期间对源文件所有的改动，都会被 Page Tracking 记录，将在 Page Copy 阶段进行 “覆盖” 订正处理。所以不用担心 Copy 期间源文件发生改变问题。

**c. Page Copy**

该阶段的主要目的是订正覆盖 FILE COPY 阶段，源文件有改动的地方，相当于处理  FILE COPY 阶段的增量数据。执行拷贝之前，会基于 tablespace ID 和 page ID 对这些页进行排序，以避免 PAGE COPY 过程中的随机读写。

因为对数据文件的拷贝已经结束，那 PAGE COPY 阶段的增量数据，将通过归档 redo log 来处理。

所以，在 PAGE COPY 阶段启动前，会开启 Redo Archiving 归档线程，将 redo log 的内容按块拷贝到归档文件中。通常来讲，归档线程的拷贝速度会快于 redo log 的生成速度。即便 redo log 生成速度要快于归档线程，在写入 redo log 时，也会等待归档线程完成拷贝，不会覆盖还未拷贝的 redo log。

Page Tacking 中的页面拷贝完成后，会获取实例的一致性位点信息，停止 Redo Archiving 同时将此时的 LSN 记为 CLONE LSN。

**d. Redo Copy**

拷贝归档文件中 CLONE FILE END LSN 与 CLONE LSN 之间的 redo log，通过重用归档 redo log 就可以将数据库恢复到一个一致的时间点 Clone LSN，也就是停止 Redo Archiving 时的那一刻。

**e. Done**

调用 snashot_end() 销毁克隆对象。



## 5. 克隆插件的限制
在使用 Clone 插件时，需注意有如下限制：
* 克隆期间，会堵塞 DDL 同样 DDL 也会堵塞克隆命令的执行。不过从 MySQL 8.0.27 开始，克隆命令就不会堵塞捐赠者上的 DDL 了。
* 克隆插件只会拷贝 innodb 引擎表中的数据，对于其他存储引擎，只会拷贝表结构。
*  克隆插件不会拷贝配置参数和 Binlog。
* 捐赠者和接受者的版本需要保持一致。不仅大版本要一样，小版本也要一样。可使用 show variables 命令查看版本。
* 远程克隆，主机操作系统和位数必须一致，可通过 version_compile_os 与 version_compile_machine 查看。
* 捐赠者和接收者都需要安装克隆插件。
* 捐赠者和接受者字符集需要一样，可通过 character_set_server 与 collation_server 查看。
* 捐赠者和接受者的参数 innodb_page_size 与 innodb_data_file_path 需要一样。
* 默认情况下，远程 clone 会在完成数据 clone 后，关闭接受者实例。需要有控制进程（如 mysqld_safe 脚本、systemctl 等）来拉起接受者实例。如果缺少控制进程，则接受者实例关闭后，无法自动启动，需要手动拉起。
* 无论是捐赠者还是接收者，同一时间只能执行一个克隆操作。


>推荐阅读：[5.6.7.14 Clone Plugin Limitations
>](https://dev.mysql.com/doc/refman/8.0/en/clone-plugin-limitations.html)


## 6. 克隆插件与 Xtrabackup 的异同
在实现上，两者都有 File Copy 和 Redo Copy 阶段，但克隆插件比 Xtrabackup 多一个 Page Copy 阶段。基于此原因，克隆插件的恢复速度比 Xtrabackup 更快。

Xtrabackup 没有 Redo Archiving 特性，可能会出现未拷贝 redo 被覆盖的情况，不过 8.0 版本也有对应的解决方案，感兴趣可以参考下文。

>推荐阅读：[Use Physical Backups With MySQL InnoDB Redo Log Archiving
>](https://www.percona.com/blog/use-physical-backups-with-mysql-innodb-redo-log-archiving/)

通过克隆出来的实例，可以直接搭建 GTID 复制，相关位点信息也会拷贝，无须额外执行 SET GLOBAL GTID_PURGED 操作。

## 7. 克隆插件相关参数
* **clone_autotune_concurrency**：是否自动调节克隆过程中并发线程数的数量，默认为 ON。如果为 OFF 则线程数等于 clone_max_concurrency 默认为 16 个。
* **clone_buffer_size**：本地克隆时，中转缓冲区的大小，默认为 4MB。缓冲区越大，备份速度越快，相应的磁盘 IO 压力也就越大。
* **clone_block_ddl：** 由 MySQL 8.0.27 版本新加入的参数，默认为 OFF 表示允许捐赠者在 Clone 期间可以执行 DDL。

* **clone_ddl_timeout：** 克隆操作需要获取备份锁，在执行 Clone 命令时，如果此时正好有 DDL 执行，则 Clone 命令会被堵塞，等待获取备份锁。等待时间最长由接收者实例上的 clone_ddl_timeout 来控制，默认为 300 秒。如果超过该参数设置的时间，那么 Clone 任务会抛出异常。如果 Clone 命令正在执行，再执行 DDL 时，此时 DDL 会被备份锁堵塞，不过 DDL 的超时时间，由 lock_wait_timeout 决定，该参数默认为 31536000 秒，既 365 天。

* **clone_donor_timeout_after_network_failure：** 在远程克隆时，如果发生网络故障，克隆操作不好马上终止，而是会等待一段时间，等待时间由该参数控制，单位分钟，默认为 5 分钟。
* **clone_delay_after_data_drop：** 指定在远程克隆操作开始时立即删除接收方 MySQL Server 实例上的现有数据后的延迟时间。延迟的目的是在从捐赠者 MySQL Server 实例克隆数据之前，为接收方主机上的文件系统提供足够的时间来释放空间。某些文件系统（例如 VxFS）在后台进程中异步释放空间。在这些文件系统上，删除现有数据后过早克隆数据可能会因空间不足而导致克隆操作失败。最大延迟时间为 3600 秒（1 小时）默认设置为 0（无延迟）。
* **clone_max_data_bandwidth：** 在远程克隆时，单个线程允许数据最大拷贝速率，单位是 MiB/s。默认为 0 既不限制。如果捐赠者有 IO 瓶颈，可通过该参数限速。
* **clone_max_data_bandwidth：** 在远程克隆时，可允许的最大网络传输速率，单位是 MiB/s。默认为 0 既不限制。如果网络带宽存在瓶颈，可通过该参数限速。
* **clone_max_concurrency：** 定义远程克隆操作的最大并发线程数。默认值为 16。更多的线程数可以提高克隆性能，但也会减少允许的并发客户端连接数，从而影响现有客户端连接的性能。此设置仅应用于接收方 MySQL 服务器实例。

>推荐阅读：[5.6.7.13 Clone System Variables
>](https://dev.mysql.com/doc/refman/8.0/en/clone-plugin-options-variables.html)