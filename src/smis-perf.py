# coding=utf-8
from __future__ import print_function

import traceback
import datetime

from timeit import default_timer as timer
import requests.packages.urllib3
import urllib3
from pywbemReq.cim_operations import WBEMConnection,CIMError
import pickle

import foglight.asp
import foglight.logging
import foglight.model
import foglight.utils
import fsm.storage

from smisutil import *
from smis_processors import *
from smis_asp import SanASP

from java.util.concurrent import TimeUnit

# Set up a logger for this Agent.
logger = foglight.logging.get_logger("smis-perf")
DEBUG = True

# A helper class from the foglight.model package that tells us whether an inventory or a
# performance collection is required.
asp = SanASP()
tracker = foglight.model.CollectionTracker(asp.inventory_frequency.seconds / 60)

def collect_performance(conn):
    logger.info("Starting performance collection")
    _start = datetime.datetime.now()
    tracker._record_stamp("last_performance_started", _start)

    arrays = getArrays(conn)
    performances = []
    for ps_array in arrays:
        cim_array_path = get_cim_array_path(ps_array.get("ElementName"))
        cim_array_inventory = pickle_load(cim_array_path)
        if cim_array_inventory is None:
            tracker.request_inventory()
            return

        __namespace = ps_array.path.namespace
        # conn.default_namespace = __namespace
        logger.info("NAMESPACE: {0}", __namespace)
        __CLASS_NAMES = getClassNames(conn, __namespace, None)

        if not hasStatisticalDataClass(conn, __namespace, __CLASS_NAMES):
            continue

        statObjectMap = getStatObjectMap(conn, __namespace)
        statAssociations = getStatAssociations(conn, __namespace)
        # isBlockStorageViewsSupported = getBlockStorageViewsSupported(conn)
        # supportedViews = getSupportedViews(conn, ps_array, isBlockStorageViewsSupported)

        # controllers = getControllers(conn, ps_array
        controllers = cim_array_inventory['controllers']
        logger.info("controllers: {0}", len(controllers))

        # fcPorts = getFcPorts(conn, ps_array, controllers)
        fcPorts = cim_array_inventory['fcPorts']
        logger.info("fc ports: {0}", len(fcPorts))

        # iscsiPorts = getIscisiPorts(conn, ps_array, controllers)
        iscsiPorts = cim_array_inventory['iscsiPorts']
        logger.info("iscsi ports: {0}", len(iscsiPorts))

        # pools = getPools(conn, ps_array)
        pools = cim_array_inventory['pools']
        logger.info("pools: {0}", len(pools))

        # disks = getDisks(conn, ps_array, controllers, supportedViews)
        disks = cim_array_inventory['disks']
        logger.info("disks: {0}", len(disks))

        # volumes = [y for x in poolVolumeMap.values() for y in x]
        poolVolumeMap = cim_array_inventory['poolVolumeMap']
        volumes = cim_array_inventory['volumes']
        logger.info("volumes: {0}", len(volumes))
        if volumes:
            logger.debug("volumes[0].tomof(): {0}", volumes[0].tomof())

        # for assoc in statAssociations:
        #     print(assoc.get("ManagedElement"))
        #     print(assoc.get("Stats"))

        controllerStats = getAllControllerStatistics(conn, controllers, statAssociations, statObjectMap)
        fcPortStats = getAllPortStatistics(conn, fcPorts, statAssociations, statObjectMap)
        logger.info("fcPortStats: {0}", len(fcPortStats))
        iscsiPortStats = getAllPortStatistics(conn, iscsiPorts, statAssociations, statObjectMap)
        logger.info("iscsiPortStats: {0}", len(iscsiPortStats))
        volumeStats = getAllVolumeStatistics(conn, volumes, statAssociations, statObjectMap)
        diskStats = getAllDiskStatistics(conn, disks, statAssociations, statObjectMap, __CLASS_NAMES)

        if len(controllerStats) > 0:
            logger.debug("controllerStatistics: {0}", controllerStats[0].tomof())
        if len(fcPortStats) > 0:
            logger.debug("fcPortStatistics: {0}", fcPortStats[0].tomof())
        if len(iscsiPortStats) > 0:
            logger.debug("iscsiPortStatistics: {0}", iscsiPortStats[0].tomof())
        if len(volumeStats) > 0:
            for vs in volumeStats:
                if vs.has_key('KBytesWritten') and vs['KBytesWritten'] > 0:
                    logger.debug("volumeStat: {0}", vs.tomof())
                    break

        if len(diskStats) > 0:
            logger.debug("diskStatistics: {0}", diskStats[0].tomof())

        statsCap = getStatsCapabilities(conn, ps_array)
        clockTickInterval = None
        if statsCap is not None:
            clockTickInterval = statsCap['ClockTickInterval']
        logger.debug("clockTickInterval:{0}", clockTickInterval)

        performances.append({'ps_array': ps_array,
            'controllerStats': controllerStats, 'fcPortStats': fcPortStats, 'iscsiPortStats': iscsiPortStats,
            'volumeStats': volumeStats, 'diskStats': diskStats, 'clockTickInterval': clockTickInterval,
            'poolVolumeMap': poolVolumeMap, 'pools': pools, 'performance_frequency':asp.performance_frequency})

    try:
        update = foglight.topology.begin_data_collection()
        model = fsm.storage.SanNasModel(data_update=update)

        for performance in performances:
            submit_performance(model, performance, tracker)

        submission = update.prepare_submission().json
        # logger.debug("submission {0} ", submission)

        model.submit(inventory_frequency=asp.inventory_frequency, performance_frequency=asp.performance_frequency)
    except Exception:
        logger.error(traceback.format_exc())
    finally:
        tracker.record_performance()

    logger.info("Performance collection completed and submitted in %d seconds" % (datetime.datetime.now() - _start).total_seconds())
    return None


def execute_request():
    logger.info('Requesting url=%s, ns=%s' % (asp.get_server_url(), asp.namespace))

    try:
        requests.packages.urllib3.disable_warnings()
        requests.packages.urllib3.disable_warnings(category=urllib3.exceptions.SSLError)
        urllib3.disable_warnings(category=urllib3.exceptions.SSLError)
        foglight.utils.disable_ssl_cert_checking()

        # Create a connection
        conn = WBEMConnection(asp.get_server_url(), asp.get_credential(), default_namespace=asp.namespace, verify=False, timeout=(60,1800))
        logger.info("conn: {0}", conn)
        detectInteropNamespace(conn)

        if tracker.last_inventory:
            collect_performance(conn)
            tracker.record_performance()
        else:
            logger.info("inventory collection is required")

    # handle any exception
    except CIMError as err:
        logger.error(traceback.format_exc())
    except Exception:
        logger.error(traceback.format_exc())
    finally:
        if conn:
            conn = None


def debug(*args):
    if DEBUG:
        print(*args)
    return None


def main():
    execute_request()
    return 0

if __name__ == '__main__':
    main()

