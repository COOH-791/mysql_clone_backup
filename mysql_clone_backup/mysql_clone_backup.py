# -*- coding: utf-8 -*-
import os
import sys
import math
import time
import uuid
import struct
import argparse
import configparser
from datetime import datetime
import subprocess
import pymysql
from pymysql import escape_string

# 独立的 Bucket 类，因为考虑要兼容性，这里 Bucket 没有集成在备份程序中 :-)
from minio_oss import Bucket

__author__ = 'huabing8023@126.com'


class MySqlCloneBackup(object):
    def __init__(self, mysql_conf_info, metadata_conf_info, backup_setting_info):
        # 元数据 tb_instance 实例 ID
        self.tb_instance_id = backup_setting_info['tb_instance_id']
        # clone 备份的目录
        self.backup_path = backup_setting_info['backup_path']
        # 全量备份保留时长
        self.storage_days = backup_setting_info['full_storage_days']
        # 日志备份保留天数
        self.binlog_storage_days = backup_setting_info['binlog_storage_days']
        # 是否开启 debug
        self.is_debug = backup_setting_info['debug']
        # 环境是否为集群成员
        self.is_cluster = backup_setting_info['is_cluster']
        # bucket 的名称
        self.bucket_name = backup_setting_info['bucket_name']
        # Binlog index 文件目录
        self.binlog_index_path = backup_setting_info['bin_index_path']

        # MySQL 备份服务的连接信息
        self.mysql_link_info = mysql_conf_info
        # 元数据中心的连接信息
        self.metadata_link_info = metadata_conf_info

        # 备份文件夹名
        self.backup_file_name = 'bak_' + str(self.tb_instance_id) + '_' + str(datetime.now().strftime('%Y%m%d%H%M%S'))
        # 获取备份任务 uuid、数据库的角色
        self.backup_uuid, self.read_only = self.get_instance_info()

    def main(self):
        """
        主调用方法，备份的阶段
        """
        # 判断是集群模式，当前是主库，那么就不在主库备份，
        if self.read_only == 0 and self.is_cluster == 'on':
            print('当前为主库，程序正常退出')
            sys.exit(0)

        # 启动 clone 备份
        self.start_clone_data()

        # 压缩备份文件
        _file_path, _file_name = self.exec_zip_command()

        # 上传备份文件
        self.write_state_metadata(3)
        bucket = Bucket(self.bucket_name)

        if bucket.upload_data(file_name=_file_name, file_path=_file_path):
            # 清理本地备份
            self.write_state_metadata(4)
            os.remove(_file_path)
        else:
            self.write_error_metadata('备份上传失败，备份当前目录：' + _file_path)

        # 确认 OSS 上文件是否存在
        is_exist, msg = bucket.get_file_info(_file_name)
        if is_exist is True:
            self.write_state_metadata(5)
            self.flush_logs()
        else:
            self.write_error_metadata(msg)

    def write_error_metadata(self, content):
        """
        任务异常，将报错信息写入 Content
        :param content:
        """
        error_sql = """update full_backup_metadata set state = "Error", info = "{0}" where backup_uuid = "{1}";""".format(
            escape_string(content), self.backup_uuid)

        self.op_service_coon(error_sql)
        self.print_debug('*' * 100)
        self.print_debug(content)
        self.print_debug('*' * 100)
        self.print_debug('出现异常，程序退出')
        sys.exit(0)

    def write_state_metadata(self, state_code):
        """
        负责写入备份状态信息 SQL:
        Doing：备份开始进行 0
        Done：备份结束 1
        Tar：tar 压缩 2
        Uploading：OSS 上传 3
        Clearing：清理本地 4
        Completed：确认完成 5
        """
        # 备份开始进行阶段写入 SQL
        doing_sql = "insert into full_backup_metadata(tb_instance_id, backup_uuid, state, backup_path, backup_name, bucket_name) " \
                    "value ('{0}', '{1}', '{2}', '{3}', '{4}', '{5}');".format(self.tb_instance_id,
                                                                               self.backup_uuid,
                                                                               'Doing',
                                                                               self.backup_path,
                                                                               str(self.backup_file_name + '.tar.gz'),
                                                                               self.bucket_name
                                                                               )

        # 备份结束阶段写入 SQL
        done_sql = "update full_backup_metadata set state = 'Done', end_time = now() where backup_uuid = '{0}';".format(
            self.backup_uuid)

        # 开始压缩
        tar_sql = "update full_backup_metadata set state = 'Tar' where backup_uuid = '{0}';".format(self.backup_uuid)

        # 开始上传 OSS
        oss_sql = "update full_backup_metadata set state = 'Uploading' where backup_uuid = '{0}';".format(
            self.backup_uuid)

        # 清理本地
        clear_sql = "update full_backup_metadata set state = 'Clearing' where backup_uuid = '{0}';".format(
            self.backup_uuid)

        # 确认完成
        completed_sql = "update full_backup_metadata set state = 'Completed' where backup_uuid = '{0}';".format(
            self.backup_uuid)

        # 根据用户
        if state_code == 0:
            self.op_service_coon(doing_sql)
        elif state_code == 1:
            self.op_service_coon(done_sql)
        elif state_code == 2:
            self.op_service_coon(tar_sql)
        elif state_code == 3:
            self.op_service_coon(oss_sql)
        elif state_code == 4:
            self.op_service_coon(clear_sql)
        elif state_code == 5:
            self.op_service_coon(completed_sql)

    def get_instance_info(self):
        """
        获取备份实例的信息，并测试元数据库能否连接，该方法只能执行一次
        :return: 备份任务 UUID、数据库角色
        """
        try:
            self.print_debug('任务初始化中...')
            self.print_debug('正在核实元数据信息...')
            # 连接备份实例，查询信息
            content = self.mysql_coon('select uuid(), @@read_only;')

            is_clone = self.mysql_coon(
                "SELECT 1 FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME = 'clone' and PLUGIN_STATUS = 'ACTIVE';")

            if len(is_clone) == 0:
                print("数据库未安装 clone 插件：install plugin clone soname 'mysql_clone.so';")
                sys.exit(1)

            # 测试元数据库是否可以连接，查询实例是否已经录入元数据库
            rs = self.op_service_coon(
                'select instance_name from tb_instance where id = {0} and is_clone = 1;'.format(self.tb_instance_id))

            if len(rs) == 0:
                print('[Error]:根据 tb_instance_id 未查询到该实例信息或备份未开启，程序退出')
                sys.exit(1)

            self.print_debug('元数据信息获取完成')
            return content[0][0], content[0][1]

        except Exception as error_message:
            print(str(error_message))
            sys.exit(1)

    def start_clone_data(self):
        """
        启动 clone 备份
        :return:
        """
        # 获取当前的时间，作为备份的文件夹名称
        clone_sql = "CLONE LOCAL DATA DIRECTORY '{0}';".format(os.path.join(self.backup_path, self.backup_file_name))
        try:
            # 写入备份信息，开始备份
            self.write_state_metadata(0)
            # 调用备份
            self.mysql_coon(clone_sql)
            # 修改备份任务状态
            self.write_state_metadata(1)
            self.print_debug('执行完成')

        except Exception as error_info:
            self.write_error_metadata(str(error_info))

    def exec_zip_command(self):
        """
        执行备份压缩
        """
        # 修改任务状态
        self.write_state_metadata(2)
        # 切换工作目录
        os.chdir(self.backup_path)
        zip_file_name = self.backup_file_name + '.tar.gz'
        command = 'tar -zcf {0} {1} --remove-files'.format(zip_file_name, self.backup_file_name)

        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        process.communicate()
        if process.returncode != 0:
            self.write_error_metadata(command)
        else:
            # 返回备份压缩文件大小
            file_size = self.bit_conversion(os.path.getsize(zip_file_name))
            size_sql = "update full_backup_metadata set backup_size = '{1}' " \
                       "where backup_uuid = '{0}';".format(self.backup_uuid, file_size)
            self.op_service_coon(size_sql)

            return os.path.join(self.backup_path, zip_file_name), zip_file_name

    def op_service_coon(self, sql_text):
        """
        与 op-service-db 数据库交互的公共方法
        :return: 结果集合
        """
        with pymysql.connect(
                host=self.metadata_link_info['host'],
                port=int(self.metadata_link_info['port']),
                user=self.metadata_link_info['user'],
                password=self.metadata_link_info['password'],
                charset=self.metadata_link_info['charset'],
                database=self.metadata_link_info['database']
        ) as cursor:
            cursor.execute(sql_text)
            content = cursor.fetchall()
            cursor.close()
        return content

    def mysql_coon(self, query_text: str):
        """
        连接备份数据库的方法，用来调用 clone 操作、查看 clone 任务
        :return: 查询结果集合
        """
        self.print_debug(query_text)
        with pymysql.connect(
                host=self.mysql_link_info['host'],
                port=int(self.mysql_link_info['port']),
                user=self.mysql_link_info['user'],
                password=self.mysql_link_info['password'],
                charset=self.mysql_link_info['charset'],
                database='information_schema',
        ) as cursor:
            cursor.execute(query_text)
            content = cursor.fetchall()
            cursor.close()
        self.print_debug('mysql_coon：执行完成')
        return content

    @staticmethod
    def load_config_file(config_path):
        """
        加载配置文件，并进行校验
        """
        try:
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            mysql_link = dict(config.items('mysql-link'))
            metadata_link = dict(config.items('metadata-link'))
            backup_conf = dict(config.items('backup-conf'))

            return mysql_link, metadata_link, backup_conf
        except configparser.NoSectionError as er:
            print('Settings Error:', er)
            sys.exit(0)

    @staticmethod
    def bit_conversion(size, dot=2):
        size = float(size)
        if 0 <= size < 1:
            human_size = str(round(size / 0.125, dot)) + ' b'
        elif 1 <= size < 1024:
            human_size = str(round(size, dot)) + ' B'
        elif math.pow(1024, 1) <= size < math.pow(1024, 2):
            human_size = str(round(size / math.pow(1024, 1), dot)) + ' KB'
        elif math.pow(1024, 2) <= size < math.pow(1024, 3):
            human_size = str(round(size / math.pow(1024, 2), dot)) + ' MB'
        elif math.pow(1024, 3) <= size < math.pow(1024, 4):
            human_size = str(round(size / math.pow(1024, 3), dot)) + ' GB'
        elif math.pow(1024, 4) <= size < math.pow(1024, 5):
            human_size = str(round(size / math.pow(1024, 4), dot)) + ' TB'
        elif math.pow(1024, 5) <= size < math.pow(1024, 6):
            human_size = str(round(size / math.pow(1024, 5), dot)) + ' PB'
        elif math.pow(1024, 6) <= size < math.pow(1024, 7):
            human_size = str(round(size / math.pow(1024, 6), dot)) + ' EB'
        elif math.pow(1024, 7) <= size < math.pow(1024, 8):
            human_size = str(round(size / math.pow(1024, 7), dot)) + ' ZB'
        elif math.pow(1024, 8) <= size < math.pow(1024, 9):
            human_size = str(round(size / math.pow(1024, 8), dot)) + ' YB'
        elif math.pow(1024, 9) <= size < math.pow(1024, 10):
            human_size = str(round(size / math.pow(1024, 9), dot)) + ' BB'
        elif math.pow(1024, 10) <= size < math.pow(1024, 11):
            human_size = str(round(size / math.pow(1024, 10), dot)) + ' NB'
        elif math.pow(1024, 11) <= size < math.pow(1024, 12):
            human_size = str(round(size / math.pow(1024, 11), dot)) + ' DB'
        elif math.pow(1024, 12) <= size:
            human_size = str(round(size / math.pow(1024, 12), dot)) + ' CB'
        else:
            raise ValueError('bit_conversion Error')
        return human_size

    @staticmethod
    def get_random_uuid():
        """
        获取随机的 UUID 作为任务 ID
        """
        return str(uuid.uuid1())

    def print_debug(self, content):
        if self.is_debug == 'on':
            print(content)
        else:
            pass

    def flush_logs(self):
        """
        备份结束后，刷新一下 Binlog 日志，主要是考虑一些边缘业务，好几天才能写满一个 Binlog
        这样会导致 Clone 全量备份结束了，日志增量还是几天前的，所以在凌晨，备份结束后，再刷新下日志，让增量日志也触发 OSS 上传
        """
        sql_text = 'flush logs;'
        try:
            self.mysql_coon(sql_text)
            self.print_debug('flush logs done')
        except Exception as err:
            print(err)


class MySQLBinlogBackup(MySqlCloneBackup):

    def binlog_main(self):
        """
        Binlog 上传调用总方法
        """
        task_key = self.get_new_load_file()
        if task_key == 'init':
            self.print_debug('调用 init')
            self.binlog_upload(self.get_mysql_index_list())
        else:
            binlog_upload_info = self.judge_upload_files(task_key)
            if len(binlog_upload_info) > 1:
                self.binlog_upload(binlog_upload_info)
            else:
                self.print_debug('无需上传')

    def judge_upload_files(self, task_key):
        """
        判断需要上传的文件列表
        """
        binlog_files = self.get_mysql_index_list()
        try:
            file_list = binlog_files[binlog_files.index(task_key) + 1::]
            if len(file_list) == 0:
                return []
            else:
                return file_list
        except ValueError as err:
            # 出现 Binlog 找不到的情况
            print(str(err))

    def binlog_upload(self, task_queue):
        """
        传入一个文件列表，负责将列表中的文件上传到 OSS
        :param task_queue:
        """
        binlog_data_queue = list()
        for file_path in task_queue:
            file_name, binlog_start_time, binlog_file_size, binlog_name = self.read_binlog_position(file_path)
            binlog_data_queue.append(
                {
                    'file_name': file_name,
                    'file_path': file_path,
                    'binlog_start_time': binlog_start_time,
                    'binlog_file_size': binlog_file_size,
                    'binlog_name': binlog_name,
                    'task_uuid': self.get_random_uuid(),
                    'bucket_name': self.bucket_name
                }
            )

        # 列出所有需要上传的文件列表
        i = 0
        while len(binlog_data_queue) > i:
            # 最后一个 Binlog 只做时间参考
            if i + 1 == len(binlog_data_queue):
                pass
            else:
                end_time = binlog_data_queue[i + 1]['binlog_start_time']
                binlog_data_queue[i]['end_time'] = end_time

                # 写入任务数据
                self.write_binlog_metadata(binlog_data_queue[i])

                # 调用上传
                bucket = Bucket(self.bucket_name)
                if bucket.upload_data(file_name=binlog_data_queue[i]['binlog_name'],
                                      file_path=binlog_data_queue[i]['file_path']):

                    self.update_binlog_metadata(binlog_data_queue[i]['task_uuid'], 1)

                    self.print_debug('日志备份上传成功:' + binlog_data_queue[i]['binlog_name'])
                else:
                    self.update_binlog_metadata(binlog_data_queue[i]['task_uuid'], 3)
                    self.print_debug('日志备份上传失败:' + binlog_data_queue[i]['binlog_name'])

                # 确认 OSS 上文件是否存在
                is_exist, msg = bucket.get_file_info(binlog_data_queue[i]['binlog_name'])

                if is_exist is True:
                    self.update_binlog_metadata(binlog_data_queue[i]['task_uuid'], 2)
                else:
                    self.update_binlog_metadata(binlog_data_queue[i]['task_uuid'], 3)

            i += 1

    def get_new_load_file(self):
        """
        从元数据中心查询最新的备份文件
        """
        sql = "select backup_path from full_backup_metadata where tb_instance_id = {0} and state = 'Completed' " \
              "and backup_type = 'binlog' order by id desc limit 1;".format(self.tb_instance_id)

        content = self.op_service_coon(sql)

        # 如果没有返回数据，表示未进行过日志备份，需要进行初始化
        if len(content) == 0:
            return 'init'
        else:
            return content[0][0]

    def get_mysql_index_list(self):
        """
        获取本地 index 文件中 binlog 的列表
        :return: Binlog 文件列表
        """
        with open(self.binlog_index_path, 'r') as r1:
            content = list(r1.readlines())

        return [i.replace('\n', '') for i in content]

    def write_binlog_metadata(self, binlog_meta_dict):
        # 备份开始进行阶段写入 SQL
        init_sql = """
        insert into full_backup_metadata(tb_instance_id, state, start_time, backup_type, backup_size, backup_path, 
        backup_name, bucket_name, backup_uuid, end_time, overdue_day) values ('{0}', '{1}', '{2}','{3}', '{4}', '{5}', 
        '{6}', '{7}', '{8}', '{9}', '{10}');
        """.format(self.tb_instance_id,
                   'Doing',
                   binlog_meta_dict['binlog_start_time'],
                   'binlog',
                   binlog_meta_dict['binlog_file_size'],
                   binlog_meta_dict['file_path'],
                   binlog_meta_dict['binlog_name'],
                   binlog_meta_dict['bucket_name'],
                   binlog_meta_dict['task_uuid'],
                   binlog_meta_dict['end_time'],
                   self.binlog_storage_days)

        self.op_service_coon(init_sql)

    def update_binlog_metadata(self, task_uuid, state_code):
        """
        修改日志文件上传的任务状态，该任务步骤只有上传所以异常处理比较简单
        """
        # 任务上传成功 SQL
        uploading_sql = "update full_backup_metadata set state = 'Uploading' where backup_uuid = '{0}';".format(
            task_uuid)

        # 确认成功 SQL
        completed_sql = "update full_backup_metadata set state = 'Completed' where backup_uuid = '{0}';".format(
            task_uuid)

        # 异常 SQL
        error_sql = "update full_backup_metadata set state = 'Error', info='上传异常' where backup_uuid = '{0}';".format(
            task_uuid)

        if state_code == 1:
            self.op_service_coon(uploading_sql)
        elif state_code == 2:
            self.op_service_coon(completed_sql)
        elif state_code == 3:
            self.op_service_coon(error_sql)

    def read_binlog_position(self, binlog_path):
        """
        解析 Binlog 第一个 Event Header 获取开始时间
        :param binlog_path:
        """

        binlog_event_header_len = 19

        binlog_file_size = self.bit_conversion(os.path.getsize(binlog_path))
        file_name = os.path.basename(binlog_path)

        with open(binlog_path, 'rb') as r:
            # read BINLOG_FILE_HEADER
            if not r.read(4) == b'\xFE\x62\x69\x6E':
                print("Error: Is not a standard binlog file format.")
                sys.exit(0)

            # read binlog header FORMAT_DESCRIPTION_EVENT
            read_byte = r.read(binlog_event_header_len)
            result = struct.unpack('=IBIIIH', read_byte)
            type_code, event_length, event_timestamp, next_position = result[1], result[3], result[0], result[4]
            binlog_start_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event_timestamp))

        binlog_name = 'log_' + str(self.tb_instance_id) + '_' + binlog_path.split('/')[-1]

        return file_name, binlog_start_time, binlog_file_size, binlog_name


if __name__ == '__main__':
    # 备份目录、实例名、实例 ID
    parser = argparse.ArgumentParser(description='A clone backup manager: __author__ = HuaBing')
    parser.add_argument('--config', '-f', type=str, help='Backup program configuration file directory.', default=None)
    parser.add_argument('--mode', '-m', type=str, help='Backup boot mode, clone or backup binlog. clone/binlog',
                        default='full')
    args = parser.parse_args()

    if not args.config:
        parser.print_help()
        sys.exit(0)

    # 加载配置文件
    mysql_conf, metadata_conf, backup_setting = MySqlCloneBackup.load_config_file(args.config)

    # 判断程序的启动方式
    if args.mode == 'full':
        clone_bak = MySqlCloneBackup(mysql_conf, metadata_conf, backup_setting)
        clone_bak.main()

    elif args.mode == 'binlog':
        binlog_bak = MySQLBinlogBackup(mysql_conf, metadata_conf, backup_setting)
        binlog_bak.binlog_main()
    else:
        print('Backup boot mode, clone or backup binlog. clone/binlog')
