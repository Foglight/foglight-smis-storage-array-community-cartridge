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
    debug("arrays:", len(arrays))

    inventories = []
    for ps_array in arrays:
        debug("array:", ps_array.path)
        debug("array:", ps_array.tomof())

        __namespace = ps_array.path.namespace
        debug("array.namespace: ", __namespace)

        # diskDrives = conn.EnumerateInstances("CIM_DiskDrive", __namespace)
        # diskDrives = [d for d in diskDrives if d.get("SystemName") == ps_array.get("Name")]
        # print("diskDrive: ", len(diskDrives))
        # for dv in diskDrives:
        #     print("driveView", dv.tomof())

        isBlockStorageViewsSupported = getBlockStorageViewsSupported(conn)
        debug("isBlockStorageViewsSupported", isBlockStorageViewsSupported)

        supportedViews = getSupportedViews(conn, ps_array, isBlockStorageViewsSupported)
        debug("supportedViews", supportedViews)

        controllers = getControllers(conn, ps_array)
        debug("controllers: ", len(controllers))

        fcPorts = getFcPorts(conn, ps_array, controllers)
        debug("fc ports : ", len(fcPorts))

        iscsiPorts = getIscisiPorts(conn, ps_array, controllers)
        debug("iscsi ports : ", len(iscsiPorts))

        pools = getPools(conn, ps_array)
        debug("pools: ", len(pools))

        disks = getDisks(conn, ps_array, controllers, supportedViews)
        debug("disks: ", len(disks))

        poolVolumeMap = getPoolVolumesMap(conn, ps_array, pools, supportedViews)
        volumes = [y for x in poolVolumeMap.values() for y in x]
        debug("volumes: ", len(volumes))

        poolDiskMap = getPoolDiskMap(conn, pools, disks)
        for k in poolDiskMap.keys():
            poolDiskPaths = poolDiskMap.get(k)
            for disk in disks:
                if poolDiskPaths.__contains__(disk.path):
                    disk.__setitem__("PoolID", k)

            poolVolumes = poolVolumeMap.get(k)
            debug('%s disks: %d, volumes: %d' % (k, len(poolDiskPaths),
                                                 len(poolVolumes) if poolVolumes else 0))

        # extents = getExtents(conn, ps_array, controllers)
        # debug("extents: ", len(extents))
        # if extents:
        #     for e in extents.values():
        #         print('extent:', e.tomof())

        # getDiskExtents getDiskToVolumeAssociation
        # print("extents: ", len(extents))

        # TODO getStorageTiers, memberToTier, volumeToTier, parityGroups

        if controllers:
            print("controller: ", controllers[0].tomof())
        if fcPorts:
            print("fcPorts[0]: ", fcPorts[0].tomof())
        if iscsiPorts:
            print("iscisiPorts[0]: ", iscsiPorts[0].tomof())
        if pools:
            print("pools[0]: ", pools[0].tomof())
        if disks:
            print("disks: ", disks[0].tomof())
        if volumes:
            print("volumes[0]: ", volumes[0].tomof())

        inventories.append({'ps_array': ps_array,
                          'controllers': controllers, 'fcPorts': fcPorts, 'iscsiPorts': iscsiPorts,
                          'pools': pools, 'disks': disks, 'volumes': volumes, 'poolDiskMap': poolDiskMap})

    update = None
    try:
        update = foglight.topology.begin_update()
        model = fsm.storage.SanNasModel(topology_update=update)

        for inventory in inventories:
            submit_inventory(model, inventory)

        model.submit(inventory_frequency=inventory_frequency,
                     performance_frequency=performance_frequency)
        update = None
    except Exception:
        # logger.error(traceback.format_exc())
        print(traceback.format_exc())
    finally:
        if update:
            update.abort()
        tracker.record_inventory()

    logger.info("Inventory collection completed and submitted in %d seconds" % round(timer() - _start))
    return None


def collect_performance(conn, tracker):
    logger.info("Starting performance collection")
    _start = timer()

    arrays = getArrays(conn)
    # arrays = arrays[1:2]
    performances = []
    for ps_array in arrays:
        __namespace = ps_array.path.namespace
        print("NAMESPACE: ", __namespace)

        if (not hasStatisticalDataClass(conn, __namespace)):
            continue

        statObjectMap = getStatObjectMap(conn, __namespace)
        statAssociations = getStatAssociations(conn, __namespace)
        debug("len(statDatas)", len(statObjectMap))
        debug("len(statAssociations)", len(statAssociations))

        isBlockStorageViewsSupported = getBlockStorageViewsSupported(conn)
        debug("isBlockStorageViewsSupported", isBlockStorageViewsSupported)

        supportedViews = getSupportedViews(conn, ps_array, isBlockStorageViewsSupported)
        debug("supportedViews", supportedViews)

        controllers = getControllers(conn, ps_array)
        debug("controllers: ", len(controllers))

        fcPorts = getFcPorts(conn, ps_array, controllers)
        debug("fc ports : ", len(fcPorts))

        iscsiPorts = getIscisiPorts(conn, ps_array, controllers)
        debug("iscsi ports : ", len(iscsiPorts))

        pools = getPools(conn, ps_array)
        debug("pools: ", len(pools))

        disks = getDisks(conn, ps_array, controllers, supportedViews)
        debug("disks: ", len(disks))
        if disks:
            print("disks[0].tomof()", disks[0].tomof())

        poolVolumeMap = getPoolVolumesMap(conn, ps_array, pools, supportedViews)
        volumes = [y for x in poolVolumeMap.values() for y in x]
        debug("volumes: ", len(volumes))
        if volumes:
            print("volumes[0].tomof()", volumes[0].tomof())

        controllerStats = []
        for c in controllers:
            controllerStat = getControllerStatistics(conn, c, statAssociations, statObjectMap)
            if len(controllerStat) > 0:
                controllerStats += controllerStat
        debug("controllerStatistics: ", len(controllerStats))

        fcPortStats = []
        for p in fcPorts:
            portStat = getPortStatistics(conn, p, statAssociations, statObjectMap)
            if len(portStat) > 0:
                fcPortStats += portStat
        debug("fcPortStats: ", len(fcPortStats))

        iscsiPortStats = []
        for p in iscsiPorts:
            portStat = getPortStatistics(conn, p, statAssociations, statObjectMap)
            if len(portStat) > 0:
                iscsiPortStats += portStat
        debug("iscsiPortStats: ", len(iscsiPortStats))

        volumeStats = []
        for v in volumes:
            volumeStat = getVolumeStatistics(conn, v, statAssociations, statObjectMap)
            if len(volumeStat) > 0:
                volumeStats += volumeStat
        debug("volumeStats: ", len(volumeStats))

        diskStats = []
        for d in disks:
            diskStat = getDiskStatistics(conn, d, statAssociations, statObjectMap)
            if len(diskStat) > 0:
                diskStats += diskStat
        debug("diskStats: ", len(diskStats))

        if (len(controllerStats) > 0):
            debug("controllerStatistics: ", controllerStats[0].tomof(), "\n")
        if (len(fcPortStats) > 0):
            print("fcPortStatistics: ", fcPortStats[0].tomof(), "\n")
        if (len(volumeStats) > 0):
            print("volumeStatistics: ", volumeStats[0].tomof(), "\n")
        if len(diskStats) > 0:
            print("diskStatistics: %s" % (diskStats[0].tomof()), "\n")

        performances.append({'ps_array': ps_array,
            'controllerStats': controllerStats, 'fcPortStats': fcPortStats, 'iscsiPortStats': iscsiPortStats,
            'volumeStats': volumeStats, 'diskStats': diskStats})

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
        debug("conn:", conn)

        # collect_inventory(conn)
        # print("="*100)
        # collect_performance(conn)

        threads = []
        # tracker = foglight.model.CollectionTracker(inventory_frequency.seconds / 60)
        # if tracker.is_inventory_recommended():
        #     logger.info("Inventory collection required")
        #     # t1 = threading.Thread(target=collect_inventory, args=(conn, tracker))
        #     # threads.append(t1)
        #     collect_inventory(conn, tracker)
        #     tracker.record_inventory()
        #
        # if tracker.last_inventory:
        #     # t2 = threading.Thread(target=collect_performance, args=(conn, tracker))
        #     # threads.append(t2)
        #     collect_performance(conn, tracker)
        #     tracker.record_performance()

        # for t in threads:
        #     t.start()
        #
        # for t in threads:
        #     t.join()

        arrays = getArrays(conn)
        debug("arrays:", len(arrays))

        for ps_array in arrays:
            debug("array:", ps_array.tomof())
            # getMaskingMappingViews(conn, ps_array)
            getSCSIProtocolControllers(conn, ps_array)
            break

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


