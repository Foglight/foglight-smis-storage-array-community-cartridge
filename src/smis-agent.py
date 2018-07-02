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
import pickle

import foglight.asp
import foglight.logging
import foglight.model
import foglight.utils
import fsm.storage

from smisutil import *
from smis_processors import *

from java.util.concurrent import TimeUnit

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
    _start = datetime.datetime.now()

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
        if maskingMappingViews is None or len(maskingMappingViews) < 1:
            _itl_start = timer()
            volumeMappingSPCs = getSCSIProtocolControllers(conn, ps_array)
            logger.info("Retrieve SCSIProtocolControllers in %d seconds" % round(timer() - _itl_start))

        array_inventory = {'ps_array': ps_array,
                          'controllers': controllers, 'fcPorts': fcPorts, 'iscsiPorts': iscsiPorts,
                          'pools': pools, 'disks': disks, 'volumes': volumes, 'poolDiskMap': poolDiskMap,
                           'poolVolumeMap': poolVolumeMap, 'volumeMappingSPCs': volumeMappingSPCs}
        inventories.append(array_inventory)

        cim_array_path = "{0}/cim_array_{1}.txt".format(foglight.get_agent_specific_directory(),
                                                        ps_array.get("ElementName"))
        pickle_dump(cim_array_path, array_inventory)

    update = None
    try:
        update = foglight.topology.begin_update()
        model = fsm.storage.SanNasModel(topology_update=update)

        for inventory in inventories:
            submit_inventory(model, inventory)

        model.submit(inventory_frequency=inventory_frequency,
                     performance_frequency=performance_frequency)

    except Exception, e:
        logger.error(e.message)
        logger.error(traceback.format_exc())
        if update:
            update.abort()
    finally:
        tracker._record_stamp("last_inventory_started", _start)
        tracker.record_inventory()

    logger.info("Inventory collection completed and submitted in %d seconds" % (datetime.datetime.now() - _start).total_seconds())
    return None


def collect_performance(conn, tracker):
    logger.info("Starting performance collection")
    _start = datetime.datetime.now()
    tracker._record_stamp("last_performance_started", _start)

    arrays = getArrays(conn)
    performances = []
    for ps_array in arrays:
        __namespace = ps_array.path.namespace
        conn.default_namespace = __namespace
        logger.info("NAMESPACE: {0}", __namespace)
        __CLASS_NAMES = getClassNames(conn, __namespace, None)

        if not hasStatisticalDataClass(conn, __namespace, __CLASS_NAMES):
            continue

        # for cl in clns:
        #     print(cl)

        statObjectMap = getStatObjectMap(conn, __namespace)
        statAssociations = getStatAssociations(conn, __namespace)
        logger.info("len(statDatas): {0}", len(statObjectMap))
        logger.info("len(statAssociations): {0}", len(statAssociations))

        isBlockStorageViewsSupported = getBlockStorageViewsSupported(conn)
        logger.info("isBlockStorageViewsSupported: {0}", isBlockStorageViewsSupported)

        supportedViews = getSupportedViews(conn, ps_array, isBlockStorageViewsSupported)
        logger.info("supportedViews: {0}", supportedViews)

        cim_array_path = "{0}/cim_array_{1}.txt".format(foglight.get_agent_specific_directory(),
                                                        ps_array.get("ElementName"))
        cim_array_inventory = pickle_load(cim_array_path)

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
        isMediaPresent = {"CIM_MediaPresent", "CIM_StorageExtent"}.issubset(__CLASS_NAMES)
        for d in disks:
            diskStat = getDiskStatistics(conn, d, statAssociations, statObjectMap, isMediaPresent)
            if len(diskStat) > 0:
                diskStats += diskStat
        logger.info("diskStats: {0}", len(diskStats))

        if len(controllerStats) > 0:
            logger.debug("controllerStatistics: {0}", controllerStats[0].tomof())
        if len(fcPortStats) > 0:
            logger.debug("fcPortStatistics: {0}", fcPortStats[0].tomof())
        if len(volumeStats) > 0:
            for vs in volumeStats:
                if vs['KBytesWritten'] > 0:
                    logger.debug("volumeStat: {0}", vs.tomof())
                    break

        if len(diskStats) > 0:
            logger.debug("diskStatistics: {0}", diskStats[0].tomof())
            # for ds in diskStats:
            #     logger.debug("diskStat: {0}", ds.tomof())

        statsCap = getStatsCapabilities(conn, ps_array)
        clockTickInterval = None
        if statsCap is not None:
            clockTickInterval = statsCap['ClockTickInterval']

        performances.append({'ps_array': ps_array,
            'controllerStats': controllerStats, 'fcPortStats': fcPortStats, 'iscsiPortStats': iscsiPortStats,
            'volumeStats': volumeStats, 'diskStats': diskStats, 'clockTickInterval': clockTickInterval,
            'poolVolumeMap': poolVolumeMap, 'pools': pools})

    try:
        update = foglight.topology.begin_data_collection()
        model = fsm.storage.SanNasModel(data_update=update)

        for performance in performances:
            submit_performance(model, performance, tracker)

        # submission = update.prepare_submission().json
        # print("submission", submission)

        model.submit(inventory_frequency=inventory_frequency,
                 performance_frequency=performance_frequency)
    except Exception:
        print(traceback.format_exc())
    finally:
        tracker.record_performance()

    logger.info("Performance collection completed and submitted in %d seconds" % (datetime.datetime.now() - _start).total_seconds())
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
        conn = WBEMConnection(server_url, creds, default_namespace=namespace, verify=False, timeout=1800)
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

def pickle_load(filename):
    f = None
    try:
        f = open(filename, 'rb')
        return pickle.load(f)
    except(IOError,EOFError):
        return None
    finally:
        if f:
            f.close()

def pickle_dump(filename, obj):
    f = open(filename, 'wb')
    pickle.dump(obj, f)
    f.close()


def debug(*args):
    if DEBUG:
        print(*args)
    return None


def queryCredential(host_url, timeoutSec):
    credQueryBuilder = foglight.services['CredentialQueryBuilderService2']
    credService = foglight.services['CleartextCredentialService3']

    query = credQueryBuilder.createQuery("StorageMonitoring")
    if query is None:
        return None
    query.addProperty("storage.collextarget", host_url)

    queryResult = credService.queryCredentials(query)
    if queryResult is not None:
        queryResult = queryResult.getResult(1, TimeUnit.MINUTES)
    creds = None if queryResult is None else queryResult.getCredentials()

    return creds


def main():
    """ Get arguments and call the execution function"""

    asp = foglight.asp.get_properties()
    server_url = getServerUrl(asp["host"], asp["port"])
    # create the credentials tuple for WBEMConnection

    creds = None
    credList = queryCredential(asp["host"], 60)
    if credList is not None and len(credList) > 0:
        for cred in credList:
            if cred.__class__.__name__.endswith("LoginPasswordCredential"):
                creds = (cred.getUsername(), cred.getPassword())
                logger.info("found credential for {0}", asp["host"])
                break

    if creds is None:
        creds = (asp["username"], asp["password"])

    # call the method to execute the request and display results
    execute_request(server_url, creds, TEST_NAMESPACE)

    return 0

if __name__ == '__main__':
    main()


