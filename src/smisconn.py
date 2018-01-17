# coding=utf-8
from __future__ import print_function


import string
import traceback
import foglight.logging
import time

from requests.exceptions import SSLError

from pywbemReq.cim_obj import CIMInstanceName, CIMInstance
from pywbemReq.cim_operations import is_subclass
from pywbemReq.cim_types import *

logger = foglight.logging.get_logger("smisconn")

class smisconn():
    def __init__(self, conn):
        self.conn = conn

    def EnumerateInstances(self, ClassName, namespace=None, **params):
        for i in range(1,3):
            try:
                instances = self.conn.EnumerateInstances(ClassName, namespace=namespace, **params)
                break
            except Exception,e:
                time.sleep(2)
        return instances