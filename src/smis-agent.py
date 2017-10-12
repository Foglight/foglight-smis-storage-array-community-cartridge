# coding=utf-8
from __future__ import print_function

import sys
import thread
import traceback
import datetime
import threading

from timeit import default_timer as timer
import requests.packages.urllib3
import urllib3
from pywbemReq.cim_operations import WBEMConnection,CIMError

import foglight.asp
import foglight.logging
import foglight.model
import foglight.utils
import fsm.storage

from smisutil import *
from smis_processors import *


# Set up a logger for this Agent.
logger = foglight.logging.get_logger("smis-agent")
TEST_NAMESPACE = 'interop'
DEBUG = True

def getCollectorInterval():
    collector_seconds = 300
    frequencies = foglight.asp.get_collector_frequencies()
    scriptPath = [k for k in frequencies.keys() if k.endswith("smis-agent.py")]
    if (scriptPath):
        collector_seconds = max(300, frequencies[scriptPath[0]])
    return collector_seconds

# Get the collection frequencies
collector_seconds = getCollectorInterval()
performance_frequency = datetime.timedelta(seconds=collector_seconds)
inventory_frequency = datetime.timedelta(seconds=collector_seconds * 5)

# A helper class from the foglight.model package that tells us whether an inventory or a
# performance collection is required.
tracker = None

def collect_inventory(conn, tracker):
    logger.info("Starting inventory collection")
    _start = timer()

    arrays = getArrays(conn)
    logger.info("arrays: {0}", len(arrays))

    inventories = []
    for ps_array in arrays:
        logger.info("array: {0} {1}", ps_array.path, ps_array.tomof())

        __namespace = ps_array.path.namespace
        logger.info("array.namespace: {0}", __namespace)

        # diskDrives = conn.EnumerateInstances("CIM_DiskDrive", __namespace)
        # diskDrives = [d for d in diskDrives if d.get("SystemName") == ps_array.get("Name")]
        # print("diskDrive: ", len(diskDrives))
        # for dv in diskDrives:
        #     print("driveView", dv.tomof())


        isBlockStorageViewsSupported = getBlockStorageViewsSupported(conn)
        logger.info("isBlockStorageViewsSupported: {0}", isBlockStorageViewsSupported)

        supportedViews = getSupportedViews(conn, ps_array, isBlockStorageViewsSupported)
        logger.info("supportedViews: {0}", supportedViews)

        controllers = getControllers(conn, ps_array)
        logger.info("controllers: {0}", len(controllers))

        fcPorts = getFcPorts(conn, ps_array, controllers)
        logger.info("fc ports: {0}", len(fcPorts))

        iscsiPorts = getIscisiPorts(conn, ps_array, controllers)
        logger.info("iscsi ports: {0}", len(iscsiPorts))

        pools = getPools(conn, ps_array)
        logger.info("pools: {0}", len(pools))

        disks = getDisks(conn, ps_array, controllers, supportedViews)
        logger.info("disks: {0}", len(disks))

        poolVolumeMap = getPoolVolumesMap(conn, ps_array, pools, supportedViews)
        volumes = [y for x in poolVolumeMap.values() for y in x]
        logger.info("volumes: {0}", len(volumes))

        poolDiskMap = getPoolDiskMap(conn, pools, disks)
        for k in poolDiskMap.keys():
            poolDiskPaths = poolDiskMap.get(k)
            for disk in disks:
                if poolDiskPaths.__contains__(disk.path):
                    disk.__setitem__("PoolID", k)

            poolVolumes = poolVolumeMap.get(k)
            logger.debug('%s disks: %d, volumes: %d' % (k, len(poolDiskPaths), len(poolVolumes) if poolVolumes else 0))

        # extents = getExtents(conn, ps_array, controllers)
        # debug("extents: ", len(extents))
        # if extents:
        #     for e in extents.values():
        #         print('extent:', e.tomof())

        # getDiskExtents getDiskToVolumeAssociation
        # print("extents: ", len(extents))

        # TODO getStorageTiers, memberToTier, volumeToTier, parityGroups

        if controllers:
            logger.debug("controller: {0}", controllers[0].tomof())
        if fcPorts:
            logger.debug("fcPorts[0]: {0}", fcPorts[0].tomof())
        if iscsiPorts:
            logger.debug("iscisiPorts[0]: {0}", iscsiPorts[0].tomof())
        if pools:
            logger.debug("pools[0]: {0}", pools[0].tomof())
        if disks:
            logger.debug("disks: {0}", disks[0].tomof())
        if volumes:
            logger.debug("volumes[0]: {0}", volumes[0].tomof())

        maskingMappingViews = getMaskingMappingViews(conn, ps_array)
        if None == maskingMappingViews or len(maskingMappingViews) < 1:
            _itl_start = timer()
            volumeMappingSPCs = getSCSIProtocolControllers(conn, ps_array)
            logger.info("Retrieve SCSIProtocolControllers in %d seconds" % round(timer() - _itl_start))

        inventories.append({'ps_array': ps_array,
                          'controllers': controllers, 'fcPorts': fcPorts, 'iscsiPorts': iscsiPorts,
                          'pools': pools, 'disks': disks, 'volumes': volumes, 'poolDiskMap': poolDiskMap,
                            'volumeMappingSPCs': volumeMappingSPCs})

    update = None
    try:
        update = foglight.topology.begin_update()
        model = fsm.storage.SanNasModel(topology_update=update)

        for inventory in inventories:
            submit_inventory(model, inventory, update)

        model.submit(inventory_frequency=inventory_frequency,
                     performance_frequency=performance_frequency)

    except Exception, e:
        logger.error(e.message)
        if update:
            update.abort()
        logger.error(traceback.format_exc())
    finally:
        tracker.record_inventory()

    logger.info("Inventory collection completed and submitted in %d seconds" % round(timer() - _start))
    return None


def collect_performance(conn, tracker):
    logger.info("Starting performance collection")
    _start = timer()

    arrays = getArrays(conn)
    performances = []
    for ps_array in arrays:
        __namespace = ps_array.path.namespace
        logger.info("NAMESPACE: {0}", __namespace)

        if (not hasStatisticalDataClass(conn, __namespace)):
            continue

        statObjectMap = getStatObjectMap(conn, __namespace)
        statAssociations = getStatAssociations(conn, __namespace)
        logger.info("len(statDatas): {0}", len(statObjectMap))
        logger.info("len(statAssociations): {0}", len(statAssociations))

        isBlockStorageViewsSupported = getBlockStorageViewsSupported(conn)
        logger.info("isBlockStorageViewsSupported: {0}", isBlockStorageViewsSupported)

        supportedViews = getSupportedViews(conn, ps_array, isBlockStorageViewsSupported)
        logger.info("supportedViews: {0}", supportedViews)

        controllers = getControllers(conn, ps_array)
        logger.info("controllers: {0}", len(controllers))

        fcPorts = getFcPorts(conn, ps_array, controllers)
        logger.info("fc ports: {0}", len(fcPorts))

        iscsiPorts = getIscisiPorts(conn, ps_array, controllers)
        logger.info("iscsi ports: {0}", len(iscsiPorts))

        pools = getPools(conn, ps_array)
        logger.info("pools: {0}", len(pools))

        disks = getDisks(conn, ps_array, controllers, supportedViews)
        logger.info("disks: {0}", len(disks))
        if disks:
            logger.debug("disks[0].tomof(): {0}", disks[0].tomof())

        poolVolumeMap = getPoolVolumesMap(conn, ps_array, pools, supportedViews)
        volumes = [y for x in poolVolumeMap.values() for y in x]
        logger.info("volumes: {0}", len(volumes))
        if volumes:
            logger.debug("volumes[0].tomof(): {0}", volumes[0].tomof())

        controllerStats = []
        for c in controllers:
            controllerStat = getControllerStatistics(conn, c, statAssociations, statObjectMap)
            if len(controllerStat) > 0:
                controllerStats += controllerStat
        logger.debug("controllerStatistics: {0}", len(controllerStats))

        fcPortStats = []
        for p in fcPorts:
            portStat = getPortStatistics(conn, p, statAssociations, statObjectMap)
            if len(portStat) > 0:
                fcPortStats += portStat
        logger.debug("fcPortStats: {0}", len(fcPortStats))

        iscsiPortStats = []
        for p in iscsiPorts:
            portStat = getPortStatistics(conn, p, statAssociations, statObjectMap)
            if len(portStat) > 0:
                iscsiPortStats += portStat
        logger.info("iscsiPortStats: {0}", len(iscsiPortStats))

        volumeStats = []
        for v in volumes:
            volumeStat = getVolumeStatistics(conn, v, statAssociations, statObjectMap)
            if len(volumeStat) > 0:
                volumeStats += volumeStat
        logger.info("volumeStats: {0}", len(volumeStats))

        diskStats = []
        for d in disks:
            diskStat = getDiskStatistics(conn, d, statAssociations, statObjectMap)
            if len(diskStat) > 0:
                diskStats += diskStat
        logger.info("diskStats: {0}", len(diskStats))

        if (len(controllerStats) > 0):
            logger.debug("controllerStatistics: {0}", controllerStats[0].tomof())
        if (len(fcPortStats) > 0):
            logger.debug("fcPortStatistics: {0}", fcPortStats[0].tomof())
        if (len(volumeStats) > 0):
            logger.debug("volumeStatistics: {0}", volumeStats[0].tomof())
        if len(diskStats) > 0:
            logger.debug("diskStatistics: {0}", diskStats[0].tomof())

        statsCap = getStatsCapabilities(conn, ps_array)
        clockTickInterval = None
        if None != statsCap:
            clockTickInterval = statsCap['ClockTickInterval']

        performances.append({'ps_array': ps_array,
            'controllerStats': controllerStats, 'fcPortStats': fcPortStats, 'iscsiPortStats': iscsiPortStats,
            'volumeStats': volumeStats, 'diskStats': diskStats, 'clockTickInterval': clockTickInterval})

    try:
        update = foglight.topology.begin_data_collection()
        model = fsm.storage.SanNasModel(data_update=update)

        for performance in performances:
            submit_performance(model, performance, tracker, update)

        # submission = update.prepare_submission().json
        # print("submission", submission)

        model.submit(inventory_frequency=inventory_frequency,
                 performance_frequency=performance_frequency)
    except Exception:
        print(traceback.format_exc())
    finally:
        tracker.record_performance()

    logger.info("Performance collection completed and submitted in %d seconds" % round(timer() - _start))
    return None


def execute_request(server_url, creds, namespace):
    print('Requesting url=%s, ns=%s' % \
        (server_url, namespace))

    try:
        requests.packages.urllib3.disable_warnings()
        requests.packages.urllib3.disable_warnings(category=urllib3.exceptions.SSLError)
        urllib3.disable_warnings(category=urllib3.exceptions.SSLError)
        foglight.utils.disable_ssl_cert_checking()

        # Create a connection
        conn = WBEMConnection(server_url, creds, default_namespace=namespace, verify=False, timeout=1200)
        logger.info("conn: {0}", conn)
        detectInteropNamespace(conn)

        tracker = foglight.model.CollectionTracker(inventory_frequency.seconds / 60)
        # collect_inventory(conn, tracker)

        if tracker.is_inventory_recommended():
            logger.info("Inventory collection required")
            collect_inventory(conn, tracker)
            tracker.record_inventory()

        if tracker.last_inventory:
            collect_performance(conn, tracker)
            tracker.record_performance()

    # handle any exception
    except CIMError as err:
        # If CIMError, display CIMError attributes
        if isinstance(err, CIMError):
            print("Operation failed: %s" % err)
            print(traceback.format_exc())
        else:
            print ("Operation failed: %s" % err)
            print(traceback.format_exc())
    except Exception:
        print(traceback.format_exc())
    finally:
        if conn:
            conn = None


def getServerUrl(host, port):
    url = 'http://'
    if port == "5989":
        url = 'https://'
    url += host + ':' + port
    return url


def debug(*args):
    if DEBUG:
        print(*args)
    return None


def main():
    """ Get arguments and call the execution function"""

    asp = foglight.asp.get_properties()
    server_url = getServerUrl(asp["host"], asp["port"])
    # create the credentials tuple for WBEMConnection
    creds = (asp["username"], asp["password"])

    # call the method to execute the request and display results
    execute_request(server_url, creds, TEST_NAMESPACE)

    return 0

if __name__ == '__main__':
    main()


