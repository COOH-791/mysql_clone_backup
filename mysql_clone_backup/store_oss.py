# -*- coding: utf-8 -*-
import time
import datetime
from minio import Minio
from minio.error import S3Error

# Bucket 连接元数据
MINIO_CONF = {
    'endpoint': '',
    'access_key': '',
    'secret_key': '',
    'secure': False
}


class Bucket(object):
    def __init__(self, bucket_name):
        # Minio 对象
        self.client = Minio(**MINIO_CONF)
        # 数据桶名称
        self.bucket_name = bucket_name

    def upload_data(self, file_name, file_path):
        """
        上传压缩后的备份文件
        :param file_name: 上传到 OSS 后文件的名称
        :param file_path: 需要上传文件的路径
        :return: 文件是否上传成功
        """
        try:
            # 调用上传文件
            self.client.fput_object(
                bucket_name=self.bucket_name,
                object_name=file_name,
                file_path=file_path,
                content_type='application/zip',
            )
            # 上传完成返回 True
            return True
        except Exception as err:
            print("[error]:", err)
            return False

    def remove_file(self, file_name):
        """
        删除单个文件
        :param file_name: 文件名称
        """
        self.client.remove_object(self.bucket_name, file_name)

    def get_file_info(self, file_name):
        """
        判断文件是否存在
        :param file_name: 文件名称
        :return: 文件是否存在, 文件名
        """
        try:
            data = self.client.stat_object(self.bucket_name, file_name)
            return True, data.object_name
        except Exception as err:
            return False, str(err)

    def download_file(self, file_name, file_path):
        """
        从 OSS 上下载文件
        :param file_name: 文件名称
        :param file_path: 保存到本地的路径
        :return: True / False
        """
        try:
            data = self.client.get_object(bucket_name=self.bucket_name, object_name=file_name)
            with open(file_path, 'wb') as file_data:
                for i in data.stream(32 * 1024):
                    file_data.write(i)
            return True

        except Exception as err:
            print("[error]:", err)
            return False


if __name__ == '__main__':
    bucket_obj = Bucket('local')

    # 上传
    bucket_obj.upload_data('binlog_test', '/data/mysql_80/logs/mysql-bin.001487')

    # 调试
    print(bucket_obj.get_file_info('clone.txt'))

    # 测试删除
    print(bucket_obj.remove_file('lone.txt'))

    # 测试下载
    bucket_obj.download_file('bak_106_20231026102557.tar.gz', '/opt/backup_server/bak_106_20231026102557.tar.gz')
