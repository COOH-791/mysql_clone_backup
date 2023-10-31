# -*- coding: utf-8 -*-
import sys
import pymysql
from pymysql import escape_string

from minio_oss import Bucket

OP_MYSQL_CONF = {
    'host': '',
    'port': 3306,
    'user': '',
    'password': '',
    'database': '',
    'charset': '',
    'Bucket': ''
}


class ClearBackupTask(object):
    def __init__(self):
        self.bucket = Bucket(OP_MYSQL_CONF['Bucket'])

    def main(self):
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

        # 刷新备份过期时间
        self.update_overdue_day()

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

    @staticmethod
    def op_service_coon(sql_text):
        """
        与 op-service-db 数据库交互的公共方法
        :return: 结果集合
        """
        with pymysql.connect(
                host=OP_MYSQL_CONF['host'],
                port=int(OP_MYSQL_CONF['port']),
                user=OP_MYSQL_CONF['user'],
                password=OP_MYSQL_CONF['password'],
                charset=OP_MYSQL_CONF['charset'],
                database=OP_MYSQL_CONF['database']
        ) as cursor:
            cursor.execute(sql_text)
            content = cursor.fetchall()
            cursor.close()
        return content


if __name__ == '__main__':
    cl = ClearBackupTask()
    cl.main()
