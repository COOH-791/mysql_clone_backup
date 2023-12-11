# -*- coding: utf-8 -*-
import configparser
from datetime import datetime
import subprocess
import pymysql

# 独立的 Bucket 类，因为考虑要兼容性，这里 Bucket 没有集成在备份程序中 :-)
from store_oss import Bucket


class RestoreDataAid(object):
    def __init__(self):
        pass

    def get_recover_time(self):
        """
        提供一个实例名，可自动计算出可恢复数据的时间点
        :return:
        """


