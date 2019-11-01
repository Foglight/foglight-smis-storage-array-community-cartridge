# coding=utf-8

import datetime

import foglight.asp
import foglight.logging
import foglight.model
import foglight.utils

from java.util.concurrent import TimeUnit

# Set up a logger for this Agent.
logger = foglight.logging.get_logger("smis-asp")

def get_collector_interval(script):
    collector_seconds = 300
    frequencies = foglight.asp.get_collector_frequencies()
    script_path = [k for k in frequencies.keys() if k.endswith(script)]
    if script_path:
        collector_seconds = max(300, frequencies[script_path[0]])
    return collector_seconds


class SanASP(object):

    def __init__(self):
        # Get the collection frequencies
        self.performance_frequency = datetime.timedelta(seconds=get_collector_interval("smis-perf.py"))
        self.inventory_frequency = datetime.timedelta(seconds=get_collector_interval("smis-agent.py"))
        self.asp = foglight.asp.get_properties()
        self.namespace = "interop"

    def get_server_url(self):
        https = None;
        if self.asp.__contains__("https"):
            https = self.asp["https"]
        if self.asp["port"] == "5989":
            https = True

        url = "https://" if https else "http://"
        url += self.asp["host"] + ':' + self.asp["port"] + "/cimom"
        return url

    def get_credential(self):
        cred_query_builder = foglight.services["CredentialQueryBuilderService2"]
        cred_service = foglight.services["CleartextCredentialService3"]

        query = cred_query_builder.createQuery("StorageMonitoring")
        if query is None:
            return None
        query.addProperty("storage.collextarget", self.asp["host"])

        query_result = cred_service.queryCredentials(query)
        if query_result is not None:
            query_result = query_result.getResult(1, TimeUnit.MINUTES)

        cred = None
        if query_result is not None:
            credentials = query_result.getCredentials()
            if credentials is not None and len(credentials) > 0:
                cred = next(c for c in credentials if c.__class__.__name__.endswith("LoginPasswordCredential"))

        if cred is not None:
            cred = (cred.getUsername(), cred.getPassword())
            logger.info("found credential for {0}", self.asp["host"])
        else:
            cred = (self.asp["username"], self.asp["password"])
        return cred

