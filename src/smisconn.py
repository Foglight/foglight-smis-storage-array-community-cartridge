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
        instances = []
        for i in range(3):
            try:
                instances = self.conn.EnumerateInstances(ClassName, namespace=namespace, **params)
                break
            except Exception,e:
                logger.warn("Failed to EnumerateInstances {0}", e.message)
        return instances

    def Associators(self, ObjectName, **params):
        comps = []
        for i in range(3):
            try:
                comps = self.conn.Associators(ObjectName, **params)
                break
            except Exception, e:
                logger.warn("Failed to Associators {0}",e.message)
                time.sleep(5)
        return comps

    def AssociatorNames(self, ObjectName, **params):
        names = []
        for i in range(3):
            try:
                names = self.conn.AssociatorNames(ObjectName, **params)
                break
            except Exception, e:
                logger.warn("Failed to AssociatorNames {0}", e.message)
        return names

    def References(self, ObjectName, **params):
        refs = []
        for i in range(3):
            try:
                refs = self.conn.References(ObjectName, **params)
                break
            except Exception, e:
                logger.warn("Failed to References {0}", e.message)
        return refs

    def EnumerateClassNames(self, namespace=None, **params):
        cnames = []
        for i in range(3):
            try:
                cnames = self.conn.EnumerateClassNames(namespace=namespace, **params)
                break
            except Exception, e:
                logger.warn("Failed to EnumerateClassNames {0}", e.message)
        return cnames

    def GetClass(self, ClassName, namespace=None, **params):
        cls = None
        for i in range(1,3):
            try:
                cls = self.conn.GetClass(ClassName, namespace=namespace, **params)
                break
            except Exception, e:
                logger.warn("Failed to GetClass {0}", e.message)
        return cls