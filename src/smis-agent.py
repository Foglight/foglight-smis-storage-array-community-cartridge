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
logger = foglight.logging.get_logger("smis-agent")
DEBUG = True

# A helper class from the foglight.model package that tells us whether an inventory or a
# performance collection is required.
asp = SanASP()
tracker = foglight.model.CollectionTracker(asp.inventory_frequency.seconds / 60)

def collect_inventory(conn):
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
        supportedViews = getSupportedViews(conn, ps_array, isBlockStorageViewsSupported)

        controllers = getControllers(conn, ps_array)
        fcPorts = getFcPorts(conn, ps_array, controllers)
        iscsiPorts = getIscisiPorts(conn, ps_array, controllers)
        pools = getPools(conn, ps_array)
        disks = getDisks(conn, ps_array, controllers, supportedViews)
        extents = {}
        if ps_array.get("Vendor") != "huawei":
            extents = getExtents(conn, ps_array, controllers)

        poolVolumeMap = getPoolVolumesMap(conn, ps_array, pools, supportedViews, extents)
        volumes = [y for x in poolVolumeMap.values() for y in x]
        logger.info("volumes: {0}", len(volumes))

        poolDiskMap = getPoolDiskMap(conn, pools, disks)
        for k in poolDiskMap.keys():
            poolDiskPaths = poolDiskMap.get(k)
            for disk in disks:
                if poolDiskPaths.__contains__(disk.path):
                    disk.__setitem__("PoolID", k)

            poolVolumes = poolVolumeMap.get(k)
            logger.info('%s disks: %d, volumes: %d' % (k, len(poolDiskPaths), len(poolVolumes) if poolVolumes else 0))

        # getDiskExtents getDiskToVolumeAssociation
        # print("extents: ", len(extents))

        # TODO getStorageTiers, memberToTier, volumeToTier, parityGroups

        if controllers:
            for ctl in controllers:
                logger.debug("controller: {0}", ctl.tomof())
        if fcPorts:
            logger.info("fcPorts[0]: {0}", fcPorts[0].tomof())
        if iscsiPorts:
            logger.debug("iscisiPorts[0]: {0}", iscsiPorts[0].tomof())
        if pools:
            logger.debug("pools[0]: {0}", pools[0].tomof())
            # for p in pools:
            #     logger.debug("pool: {0}", p.tomof())
        if disks:
            logger.info("disks: {0}", disks[0].tomof())
        if volumes:
            logger.info("volumes[0]: {0}", volumes[0].tomof())

        # maskingMappingViews = getMaskingMappingViews(conn, ps_array)
        # if maskingMappingViews is None or len(maskingMappingViews) < 1:
        _itl_start = timer()
        volumeMappingSPCs = getSCSIProtocolControllers(conn, ps_array)
        logger.info("Retrieve SCSIProtocolControllers in %d seconds" % round(timer() - _itl_start))

        array_inventory = {'ps_array': ps_array,
                          'controllers': controllers, 'fcPorts': fcPorts, 'iscsiPorts': iscsiPorts,
                          'pools': pools, 'disks': disks, 'volumes': volumes, 'poolDiskMap': poolDiskMap,
                           'poolVolumeMap': poolVolumeMap, 'volumeMappingSPCs': volumeMappingSPCs}
        inventories.append(array_inventory)

        cim_array_path = get_cim_array_path(ps_array.get("ElementName"))
        pickle_dump(cim_array_path, array_inventory)

    update = None
    try:
        update = foglight.topology.begin_update()
        model = fsm.storage.SanNasModel(topology_update=update)

        for inventory in inventories:
            submit_inventory(model, inventory)

        submit_data = update.prepare_submission()
        # logger.debug("submit inventory data: {0}", submit_data.json)

        model.submit(inventory_frequency=asp.inventory_frequency, performance_frequency=asp.performance_frequency)

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

        logger.info("Inventory collection required")
        collect_inventory(conn)

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


