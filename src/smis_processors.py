# coding=utf-8
from __future__ import print_function

import traceback
import datetime
import foglight.asp
import foglight.logging
import foglight.model
import foglight.utils
import fsm.storage

from smisutil import *

# Set up a logger for this Agent.
logger = foglight.logging.get_logger("smis-agent")


def processArray(sanNasModel, cim_array):
    # Here is the array we're creating.
    array = sanNasModel.get_storage_array(
        cim_array.get("SerialID"), cim_array.get("Vendor"))

    array.set_name(cim_array.get("ElementName"))
    array.set_model(cim_array.get("Model"))
    array.set_product_name(cim_array.get("Product"))

    return array


def processControllers(array, cim_controllers):
    for c in cim_controllers:
        controller = array.get_controller(c["ElementName"].upper())
        # print(c.tomof())

        if c.has_key("IPAddress"):
            controller.set_property("ip", c["IPAddress"])

        if c.has_key("NetworkName"):
            controller.set_property("networkName", c["NetworkName"])

        # SoftwareRev
    return None


def processFcPorts(array, cim_fcPorts):
    for p in cim_fcPorts:
        # Note: Port ID must be globally unique, they are not specific to a single array
        try:
            # print("port: ", p.tomof())
            wwn = p.get("PermanentAddress")
            if (None == wwn): continue

            port = array.get_port("FC", wwn)
            port.set_property("name", wwn.lower())
            port.set_property("alias", p.get("ElementName"))

            controllerName = p.get("SystemName")
            controller = array.get_controller(controllerName.upper())
            port.associate_with(controller)
        except Exception,e:
            print(traceback.format_exc())
    return None


def processIscsiPorts(array, cim_iscsiPorts):
    for p in cim_iscsiPorts:
        wwn = p.get("PermanentAddress")
        if (None == wwn): continue

        port = array.get_port("ISCSI", wwn)
        port.set_property("name", p["ElementName"])

        controllerName = p["SystemName"]
        controller = array.get_controller(controllerName.upper())
        port.associate_with(controller)
    return None


def processPools(array, cim_pools):
    poolsMap = {}
    for p in cim_pools:
        poolID = p.get("InstanceID")
        pool = array.get_pool(poolID)
        pool.set_property("name", p.get("ElementName"))

        poolsMap[poolID] = pool
    return poolsMap


def processVolumes(array, cim_volumes, poolsMap):
    for v in cim_volumes:
        # print(v.tomof())

        lun = array.get_lun(v["DeviceID"])

        lun.set_label("Volume")   # so the UI knows to call these "Volumes"
        lun.set_property("name", v["ElementName"])

        pool = poolsMap[v["PoolID"]]
        lun.associate_with(pool)

        if (v.has_key("ThinlyProvisioned")):
            lun.set_property("isThinProvisioned", bool(v["ThinlyProvisioned"]))

        # Allocated
        # Capacity
        # RawCapacity
        # setProtection
        # setIsThinProvisioned

        # I *believe* that the size reported here is the advertised size of the LUN
        # not the actual size.
        # lun.set_property("advertisedSize", long(v["size"]) / 1024 / 1024)
        # pv = ps_array.get_volume(v["name"], space=True)
        # lun.set_property("protection", ps_array.get_volume(pv["name"], protect=True))
    return None


def processDisks(array, cim_disks, poolsMap):
    for d in cim_disks:
        # print(d.tomof())
        disk = array.get_physical_disk(d["DeviceID"].upper())
        disk.set_property("name", d["Name"])

        if d.has_key("PoolID"):
            poolID = d["PoolID"]
            pool = poolsMap[poolID]
            disk.associate_with(pool)

        # Model
        # Vendor
        # Capacity
        # Role
        # Rpm
        # diskInterface
        # disk.set_property("diskInterface", d["DiskType"])
        # disk.set_property("size", long(d["capacity"]) / 1024 / 1024)
    return None

def submit_inventory(sanNasModel, inventory):
    cim_array = inventory['ps_array']
    cim_controllers = inventory['controllers']
    cim_fcPorts = inventory['fcPorts']
    cim_iscsiPorts = inventory['iscsiPorts']
    cim_pools = inventory['pools']
    cim_volumes = inventory['volumes']
    cim_disks = inventory['disks']

    array = processArray(sanNasModel, cim_array)
    processControllers(array, cim_controllers)
    processFcPorts(array, cim_fcPorts)
    processIscsiPorts(array, cim_iscsiPorts)
    poolsMap = processPools(array, cim_pools)
    processVolumes(array, cim_volumes, poolsMap)
    processDisks(array, cim_disks, poolsMap)

    return None


#-----------------------------------------------------------------------------------------------------------------------


def processControllerStats(array, controllerStats, _tracker):
    for cStat in controllerStats:
        try:
            statID = cStat.get('statID')
            controller = array.get_controller(statID)

            if not controller:
                logger.verbose("Discovered new Controller {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            controller.set_metric("bytesReadBlock", long(cStat.get("KBytesRead")))
            controller.set_metric("bytesWriteBlock", long(cStat.get("KBytesWritten")))
            controller.set_metric("bytesTotalBlock", long(cStat.get("KbytesTransferred")))
            controller.set_metric("opsReadBlock", long(cStat.get("ReadIOs")))
            controller.set_metric("opsWriteBlock", long(cStat.get("WriteIOs")))
            controller.set_metric("opsTotalBlock", long(cStat.get("TotalIOs")))
            state = str(cStat.get("OperationalStatus").__iter__().next())
            controller.set_state(state)

            # busyTicks = long(cStat.get("IOTimeCounter"))
        except Exception,e:
            print(traceback.format_exc())
    return None


def processFcPortStats(array, fcPortStats, _tracker):
    for pStat in fcPortStats:
        try:
            statID = pStat.get('statID')
            port = array.get_port("FC", statID)

            if not port:
                logger.verbose("Discovered new FC port {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            port.set_metric("currentSpeedMb", 0)
            state = str(pStat.get("OperationalStatus").__iter__().next())
            port.set_state(state)

            if (None != pStat.get("KBytesRead")):
                port.set_metric("bytesRead", long(pStat.get("KBytesRead")))

            if (None != pStat.get("KBytesWritten")):
                port.set_metric("bytesWrite", long(pStat.get("KBytesWritten")))

            if (None != pStat.get("KbytesTransferred")):
                port.set_metric("bytesTotal", long(pStat.get("KbytesTransferred")))

            if (None != pStat.get("ReadIOs")):
                port.set_metric("opsRead", long(pStat.get("ReadIOs")))

            if (None != pStat.get("WriteIOs")):
                port.set_metric("opsWrite", long(pStat.get("WriteIOs")))

            if (None != pStat.get("TotalIOs")):
                port.set_metric("opsTotal", long(pStat.get("TotalIOs")))

        except Exception,e:
            print(traceback.format_exc())
    return None


def processIscsiPortStats(array, iscsiPortStats, _tracker):
    for pStat in iscsiPortStats:
        try:
            statID = pStat.get('statID')
            port = array.get_port("ISCSI", statID)

            if not port:
                logger.verbose("Discovered new ISCSI port {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            port.set_metric("currentSpeedMb", 0)
            state = str(pStat.get("OperationalStatus").__iter__().next())
            port.set_state(state)

            port.set_metric("bytesRead", long(pStat.get("KBytesRead")))
            port.set_metric("bytesWrite", long(pStat.get("KBytesWritten")))
            port.set_metric("bytesTotal", long(pStat.get("KbytesTransferred")))
            port.set_metric("opsRead", long(pStat.get("ReadIOs")))
            port.set_metric("opsWrite", long(pStat.get("WriteIOs")))
            port.set_metric("opsTotal", long(pStat.get("TotalIOs")))
        except Exception,e:
            print(traceback.format_exc())
    return None


def processVolumeStats(array, volumeStats, _tracker):
    for vStat in volumeStats:
        try:
            statID = vStat.get('statID')
            volume = array.get_lun(statID)

            if not volume:
                logger.verbose("Discovered new volume {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            state = str(vStat.get("OperationalStatus").__iter__().next())
            volume.set_state(state)

            volume.set_metric("bytesRead", long(vStat.get("KBytesRead")))
            volume.set_metric("bytesWrite", long(vStat.get("KBytesWritten")))
            volume.set_metric("bytesTotal", long(vStat.get("KbytesTransferred")))
            volume.set_metric("opsRead", long(vStat.get("ReadIOs")))
            volume.set_metric("opsWrite", long(vStat.get("WriteIOs")))
            volume.set_metric("opsTotal", long(vStat.get("TotalIOs")))
        except Exception,e:
            print(traceback.format_exc())
    return None


def processDiskStats(array, diskStats, _tracker):
    for dStat in diskStats:
        try:
            statID = dStat.get('statID')
            disk = array.get_physical_disk(statID)

            if not disk:
                logger.verbose("Discovered new Disk {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            state = str(dStat.get("OperationalStatus").__iter__().next())
            disk.set_state(state)

            disk.set_metric("bytesRead", long(dStat.get("KBytesRead")))
            disk.set_metric("bytesWrite", long(dStat.get("KBytesWritten")))
            disk.set_metric("bytesTotal", long(dStat.get("KbytesTransferred")))
            disk.set_metric("opsRead", long(dStat.get("ReadIOs")))
            disk.set_metric("opsWrite", long(dStat.get("WriteIOs")))
            disk.set_metric("opsTotal", long(dStat.get("TotalIOs")))
        except Exception, e:
            print(traceback.format_exc())
    return None


def submit_performance(model, performance, _tracker):
    ps_array = performance['ps_array']
    controllerStats = performance['controllerStats']
    fcPortStats = performance['fcPortStats']
    iscsiPortStats = performance['iscsiPortStats']
    volumeStats = performance['volumeStats']
    diskStats = performance['diskStats']

    print("getArray", ps_array.get("SerialID"), ps_array.get("Vendor"))
    array = model.get_storage_array(
        ps_array.get("SerialID"), ps_array.get("Vendor"))

    processControllerStats(array, controllerStats, _tracker)
    processFcPortStats(array, fcPortStats, _tracker)
    processIscsiPortStats(array, iscsiPortStats, _tracker)
    processVolumeStats(array, volumeStats, _tracker)
    processDiskStats(array, diskStats, _tracker)

    return None