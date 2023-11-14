# -*- coding: utf-8 -*-
import sys
import pymysql
import configparser
from pymysql import escape_string

# 调用 OSS 控制类
from store_oss import Bucket

# 如果要配置定时任务，这里需要写绝对路径
CONFIG_PATH = './clone.ini'


def load_config_file(config_path):
    """
    加载配置文件
    """
    try:
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        metadata_link = dict(config.items('metadata-link'))
        backup_conf = dict(config.items('backup-conf'))

        return metadata_link, backup_conf
    except configparser.NoSectionError as er:
        print('Settings Error:', er)
        sys.exit(0)


class ClearBackupTask(object):
    def __init__(self):
        # 读取配置文件
        self.metadata_link, self.backup_conf = load_config_file(CONFIG_PATH)
        # 初始化 OSS
        self.bucket = Bucket(self.backup_conf['bucket_name'])

    def main(self):
        # 刷新备份过期时间
        self.update_overdue_day()

        # 开始备份清理
        remove_file_list = self.get_overdue_list()

        for i in remove_file_list:
            task_id = i['task_id']
            file_name = i['backup_name']

            # 执行删除
            self.bucket.remove_file(file_name)

            # 确认是否删除成功
            if self.bucket.get_file_info(file_name)[0] is False:
                self.update_backup_state(task_id)
            else:
                print('删除任务失败')

    def get_overdue_list(self):
        """
        获取已经过期备份的列表
        """
        sql_text = """select id,backup_name from full_backup_metadata 
        where state = 'Completed' and is_delete = 0 and overdue_day = 0;"""

        file_list = list()

        for i in self.op_service_coon(sql_text):
            file_list.append(
                {
                    'task_id': i[0],
                    'backup_name': i[1]
                }
            )

        return file_list

    def update_overdue_day(self):
        sql_text = """update full_backup_metadata set overdue_day = overdue_day - 1 where overdue_day >= 1;"""
        self.op_service_coon(sql_text)

    def update_backup_state(self, task_id):
        sql_text = """update full_backup_metadata set is_delete = 1, state = 'Expiration' where id = {0};""".format(
            task_id)
        self.op_service_coon(sql_text)

    def op_service_coon(self, sql_text):
        """
        与 op-service-db 数据库交互的公共方法
        :return: 结果集合
        """
        with pymysql.connect(
                host=self.metadata_link['host'],
                port=int(self.metadata_link['port']),
                user=self.metadata_link['user'],
                password=self.metadata_link['password'],
                charset=self.metadata_link['charset'],
                database=self.metadata_link['database']
        ) as cursor:
            cursor.execute(sql_text)
            content = cursor.fetchall()
            cursor.close()
        return content


if __name__ == '__main__':
    cl = ClearBackupTask()
    cl.main()
