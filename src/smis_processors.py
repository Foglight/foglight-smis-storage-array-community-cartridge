# coding=utf-8
from __future__ import print_function

import traceback
import datetime
import pickle

import foglight
import foglight.asp
import foglight.logging
import foglight.model
import foglight.utils
import fsm.storage
from java.util import ArrayList

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
        controllerName = c["Name"]
        if c.has_key("ElementName"):
            controllerName = c["ElementName"]

        controller = array.get_controller(controllerName.upper())
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

            controllerName = p.get("ControllerName")
            controller = array.get_controller(controllerName.upper())
            port.associate_with(controller)
        except Exception,e:
            logger.error("Failed to process FC ports {0}", traceback.format_exc())
    return None


def processIscsiPorts(array, cim_iscsiPorts):
    for p in cim_iscsiPorts:
        wwn = p.get("PermanentAddress")
        if (None == wwn): continue

        port = array.get_port("ISCSI", wwn)
        port.set_property("name", p["ElementName"])

        controllerName = p["ControllerName"]
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
    logger.info("processVolumes start")
    for v in cim_volumes:
        try:
            print(v.tomof())

            lun = array.get_lun(v["DeviceID"])

            lun.set_label("Lun")   # so the UI knows to call these "Volumes"
            _name = v["ElementName"]
            if v.has_key("Caption") and v["Caption"] != None:
                _name = v["Caption"]
            lun.set_property("name", _name)

            pool = poolsMap[v["PoolID"]]
            lun.associate_with(pool)

            isThinProvisioned = False
            if (v.has_key("ThinlyProvisioned")):
                isThinProvisioned = bool(v["ThinlyProvisioned"])
                lun.set_property("isThinProvisioned", isThinProvisioned)

            blockSize = 0 if not v.has_key("BlockSize") else v["BlockSize"]
            consumableBlocks = v["ConsumableBlocks"]
            numberOfBlocks = v["NumberOfBlocks"]
            logicalBytes = 0
            if consumableBlocks == 0:
                logicalBytes = numberOfBlocks * blockSize
            else:
                logicalBytes = consumableBlocks * blockSize
            size = long(logicalBytes / 1024 / 1024)
            lun.set_property("size", size)
            lun.set_property("advertisedSize", size)
            # lun.set_property("rawCapacity", size)
            # lun.set_property("allocatedSize", size)

            if isThinProvisioned:
                consumedBytes = 0
                if v.has_key("ConsumedBytes"):
                    consumedBytes = v["ConsumedBytes"]
                if consumedBytes > logicalBytes:
                    logger.warn("Thin SALD over-consumed {0} : {1} > {2}", v["ElementName"], consumedBytes, logicalBytes)
                if 0 <= consumedBytes:
                    lun.set_property("advertisedSize", long(consumedBytes / 1024 / 1024))

            # RawCapacity
            # setProtection
        except Exception, e:
            logger.error(e.message)
    logger.info("processVolumes end")
    return None


def processDisks(array, cim_disks, poolsMap):
    for d in cim_disks:
        # print(d.tomof())
        disk = array.get_physical_disk(d["DeviceID"].upper())

        diskName = None
        if d.has_key("ElementName"):
            diskName = d["ElementName"]
        if None == diskName:
            diskName = d["Name"]
        disk.set_property("name", diskName)

        if d.has_key("PoolID"):
            poolID = d["PoolID"]
            pool = poolsMap[poolID]
            disk.associate_with(pool)

        role = "Disk"
        if d.has_key("IsSpare"):
            isSpare = d.get("IsSpare")
            if None != isSpare or bool(isSpare) == True:
                role = "Spare"
        disk.set_property("role", role)

        if d.has_key("Rpm"):
            disk.set_property("rpm", str(d.get("Rpm")))

        if d.has_key("Model"):
            disk.set_property("modelNumber", str(d.get("Model")))

        if d.has_key("Vendor"):
            disk.set_property("vendorName", str(d.get("Vendor")))

        diskInterface = ""
        if d.has_key("DiskType"):
            diskInterface = str(d.get("DiskType"))
        if diskInterface != "" and d.has_key("DeviceType"):
            diskInterface = str(d.get("DeviceType"))
        disk.set_property("diskInterface", diskInterface)

        if d.has_key("Capacity"):
            disk.set_property("size", d.get("Capacity") / 1024 / 1024)

    return None

class SanCorrelationPath():
    def __init__(self, devicePath, targetPort, lun):
        self.devicePath = devicePath
        self.targetPort = targetPort
        self.lun = lun


def processITLs(array, cim_volumeMappingSPCs, update):
    itl0s = {}
    itl1s = {}
    if None == cim_volumeMappingSPCs:
        return
    # print("len(volumePath):", len(cim_volumeMappingSPCs.keys()))
    for volumePath in cim_volumeMappingSPCs.keys():
        # print(volumePath)
        spcs = cim_volumeMappingSPCs[volumePath]
        for spc in spcs:
            storHardwareIDs = spc.get("storHardwareIDs")
            ports = spc.get("ports")
            pcfus = spc.get("pcfus")

            # print(ports[0].tomof())
            # print(pcfus[0].tomof())

            for pcfu in pcfus:
                deviceNumber = pcfu.get("DeviceNumber")
                volumePath = pcfu.path.get("Dependent")
                lunId = volumePath.get("DeviceID")

                if None == ports:
                    continue
                for port in ports:
                    portwwn = port.get("PermanentAddress").lower()
                    portType = 'FC' if port.get("CreationClassName").lower().endswith("fcport") else "ISCSI"

                    if not itl0s.__contains__(portwwn):
                        itl0 = {
                            'lun': lunId,
                            'devicePath': portwwn,
                        }
                        itl0s[portwwn] = itl0

                    if None == storHardwareIDs:
                        continue
                    for hardwareId in storHardwareIDs:
                        storageId = hardwareId.get("StorageID").lower()
                        devicePath = "%s\t%s:%s" % (storageId, portwwn, deviceNumber)

                        if not itl1s.__contains__(devicePath):
                            itl1 = {
                                'lun': lunId,
                                'targetPort': portwwn,
                                'targetPortType': portType,
                                'devicePath': devicePath
                            }
                            itl1s[devicePath] = itl1


    itl1s = sorted(itl1s.values(), key=lambda d : d['devicePath'])
    logger.info('itl1s:%d' % len(itl1s))

    itl1paths = ArrayList()
    itl0paths = ArrayList()
    for itl1 in itl1s:
        # print(itl1)
        lunKey = foglight.topology.make_object_key("SanLun", {
            "deviceID": itl1['lun'],
            "storageSupplier": array._key()
        })

        portType = itl1['targetPortType'].upper()
        if portType == "FC":
            targetPortType = "SanStorageSupplierPortFC"
        elif portType == "ISCSI":
            targetPortType = "SanStorageSupplierPortISCSI"
        targetPortKey = foglight.topology.make_object_key(targetPortType, {
            "wwn": itl1['targetPort']
        })

        itl1path = update.create_data_object("SanCorrelationPath", {
            'devicePath': itl1['devicePath'],
            'lun': lunKey,
            'targetPort': targetPortKey
        })
        itl1paths.add(itl1path._delegate)

    logger.info('itl0s:%d' % len(itl0s))
    for itl0 in itl0s.values():
        # print(itl0)

        lunKey = foglight.topology.make_object_key("SanLun", {
            "deviceID": itl0['lun'],
            "storageSupplier": array._key()
        })

        itl0path = update.create_data_object("SanCorrelationPath", {
            'devicePath': itl0['devicePath'],
            'lun': lunKey
        })
        itl0paths.add(itl0path._delegate)

    _array = update.get_object(array._key())
    _array.set_observation_value("ITLs1", itl1paths)
    _array.set_observation_value("ITLs0", itl0paths)

    return None


def submit_inventory(sanNasModel, inventory, update):
    logger.info("submit_inventory start")
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

    volume_mapping_spcs_path = "{0}/volume_mapping_spcs_{1}.txt".format(foglight.get_agent_specific_directory(),
                                                                        cim_array["SerialID"])
    pickle_dump(volume_mapping_spcs_path, inventory['volumeMappingSPCs'])

    logger.info("submit_inventory end")
    return None


#-----------------------------------------------------------------------------------------------------------------------


def processControllerStats(array, controllerStats, lastStats, _tracker):
    lastStatMap = {s['statID'] : s for s in lastStats}

    for cStat in controllerStats:
        try:
            statID = cStat.get('statID')
            if not lastStatMap.has_key(statID):
                continue
            lastStat = lastStatMap[statID]
            durationInt = __getDuration(cStat, lastStat)

            controller = array.get_controller(statID)

            if not controller:
                logger.verbose("Discovered new Controller {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            controller.set_metric("bytesReadBlock",
                                  __getStatValue('KBytesRead', cStat, lastStat, durationInt, 1024))
            controller.set_metric("bytesWriteBlock",
                                  __getStatValue('KBytesWritten', cStat, lastStat, durationInt, 1024))
            controller.set_metric("bytesTotalBlock",
                                  __getStatValue('KbytesTransferred', cStat, lastStat, durationInt, 1024))

            opsTotal = __getStatValue('TotalIOs', cStat, lastStat, 1)
            controller.set_metric("opsReadBlock", __getStatValue('ReadIOs', cStat, lastStat, durationInt))
            controller.set_metric("opsWriteBlock", __getStatValue('WriteIOs', cStat, lastStat, durationInt))
            controller.set_metric("opsTotalBlock", opsTotal / durationInt)

            ioTimeCounter = __getStatValue('IOTimeCounter', cStat, lastStat, 1)
            if ioTimeCounter > 0 and opsTotal > 0:
                controller.set_metric("latencyTotalBlock", ioTimeCounter / opsTotal)

            state = str(convertCIMOperationalStatus(cStat.get("OperationalStatus")))
            controller.set_state(state)

            # busyTicks = long(cStat.get("IOTimeCounter"))
        except Exception,e:
            logger.error(traceback.format_exc())
    return None


def processFcPortStats(array, fcPortStats, lastStats, _tracker, update):
    lastStatMap = {s['statID']: s for s in lastStats}

    for pStat in fcPortStats:
        try:
            statID = pStat.get('statID')
            if not lastStatMap.has_key(statID):
                continue
            lastStat = lastStatMap[statID]
            durationInt = __getDuration(pStat, lastStat)

            port = array.get_port("FC", statID)

            if not port:
                logger.verbose("Discovered new FC port {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            currentSpeed = pStat.get("Speed") / 1024 / 1024
            maxSpeed = pStat.get("MaxSpeed") / 1024 / 1024

            port.set_metric("currentSpeedMb", currentSpeed)
            port.set_metric("maxSpeedMb", maxSpeed)

            state = str(convertCIMOperationalStatus(pStat.get("OperationalStatus")))
            port.set_state(state)

            bytesRead = __getStatValue('KBytesRead', pStat, lastStat, durationInt, 1024)
            bytesWrite = __getStatValue('KBytesWritten', pStat, lastStat, durationInt, 1024)
            bytesTotal = __getStatValue('KbytesTransferred', pStat, lastStat, durationInt, 1024)

            port.set_metric("bytesRead", bytesRead)
            port.set_metric("bytesWrite", bytesWrite)
            port.set_metric("bytesTotal", bytesTotal)

            port.set_metric("bytesReadUtilization",
                            computeUtilization(bytesRead, currentSpeed, durationInt))
            port.set_metric("bytesWriteUtilization",
                            computeUtilization(bytesWrite, currentSpeed, durationInt))

            port.set_metric("opsRead",
                            __getStatValue('ReadIOs', pStat, lastStat, durationInt))
            port.set_metric("opsWrite",
                            __getStatValue('WriteIOs', pStat, lastStat, durationInt))
            port.set_metric("opsTotal",
                            __getStatValue('TotalIOs', pStat, lastStat, durationInt))

        except Exception,e:
            logger.error(traceback.format_exc())
    return None


def processIscsiPortStats(array, iscsiPortStats, lastStats, _tracker):
    lastStatMap = {s['statID']: s for s in lastStats}

    for pStat in iscsiPortStats:
        try:
            statID = pStat.get('statID')
            if not lastStatMap.has_key(statID):
                continue
            lastStat = lastStatMap[statID]
            durationInt = __getDuration(pStat, lastStat)

            port = array.get_port("ISCSI", statID)

            if not port:
                logger.verbose("Discovered new ISCSI port {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            currentSpeed = pStat.get("Speed") / 1024 / 1024
            maxSpeed = pStat.get("MaxSpeed") / 1024 / 1024

            port.set_metric("currentSpeedMb", currentSpeed)
            port.set_metric("maxSpeedMb", maxSpeed)

            state = str(convertCIMOperationalStatus(pStat.get("OperationalStatus")))
            port.set_state(state)

            bytesRead = __getStatValue('KBytesRead', pStat, lastStat, durationInt, 1024)
            bytesWrite = __getStatValue('KBytesWritten', pStat, lastStat, durationInt, 1024)
            bytesTotal = __getStatValue('KbytesTransferred', pStat, lastStat, durationInt, 1024)

            port.set_metric("bytesRead", bytesRead)
            port.set_metric("bytesWrite", bytesWrite)
            port.set_metric("bytesTotal", bytesTotal)

            port.set_metric("bytesReadUtilization",
                            computeUtilization(bytesRead, currentSpeed, durationInt))
            port.set_metric("bytesWriteUtilization",
                            computeUtilization(bytesWrite, currentSpeed, durationInt))

            port.set_metric("opsRead",
                            __getStatValue('ReadIOs', pStat, lastStat, durationInt))
            port.set_metric("opsWrite",
                            __getStatValue('WriteIOs', pStat, lastStat, durationInt))
            port.set_metric("opsTotal",
                            __getStatValue('TotalIOs', pStat, lastStat, durationInt))

        except Exception,e:
            logger.error(traceback.format_exc())
    return None


def processVolumeStats(array, volumeStats, lastStats, _tracker, clockTickInterval):
    lastStatMap = {s['statID']: s for s in lastStats}

    for vStat in volumeStats:
        try:
            statID = vStat.get('statID')
            if not lastStatMap.has_key(statID):
                continue
            lastStat = lastStatMap[statID]
            durationInt = __getDuration(vStat, lastStat)

            volume = array.get_lun(statID)

            if not volume:
                logger.verbose("Discovered new volume {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            state = str(convertCIMOperationalStatus(vStat.get("OperationalStatus")))
            volume.set_state(state)

            volume.set_metric("bytesRead",
                              __getStatValue('KBytesRead', vStat, lastStat, durationInt, 1024))
            volume.set_metric("bytesWrite",
                              __getStatValue('KBytesWritten', vStat, lastStat, durationInt, 1024))
            volume.set_metric("bytesTotal",
                              __getStatValue('KbytesTransferred', vStat, lastStat, durationInt, 1024))


            opsRead = __getStatValue('ReadIOs', vStat, lastStat, 1)
            opsWrite = __getStatValue('WriteIOs', vStat, lastStat, 1)
            opsTotal = __getStatValue('TotalIOs', vStat, lastStat, 1)
            readHitIos = __getStatValue('ReadHitIOs', vStat, lastStat, 1)
            writeHitIos = __getStatValue('KBytesRead', vStat, lastStat, 1)
            totalHitIos = readHitIos + writeHitIos

            readIOTimeCounter = __getStatValue('ReadIOTimeCounter', vStat, lastStat, 1)
            writeIOTimeCounter = __getStatValue('WriteIOTimeCounter', vStat, lastStat, 1)
            ioTimeCounter = __getStatValue('IOTimeCounter', vStat, lastStat, 1)
            idleTimeCounter = __getStatValue('IdleTimeCounter', vStat, lastStat, 1)

            volume.set_metric("opsRead", opsRead / durationInt)
            volume.set_metric("opsWrite", opsWrite / durationInt)
            volume.set_metric("opsTotal", opsTotal / durationInt)

            if None != clockTickInterval and clockTickInterval > 0:
                if readIOTimeCounter > 0 and opsRead > 0:
                    volume.set_metric("latencyRead", readIOTimeCounter / opsRead * clockTickInterval / 1000)
                if writeIOTimeCounter > 0 and opsWrite > 0:
                    volume.set_metric("latencyWrite", writeIOTimeCounter / opsWrite * clockTickInterval / 1000)
                if ioTimeCounter > 0 and opsTotal > 0:
                    volume.set_metric("latencyTotal", ioTimeCounter / opsTotal * clockTickInterval / 1000)

                durationTimeCounter = durationInt * 10^6 / clockTickInterval
                if (None == idleTimeCounter or 0 == idleTimeCounter) and durationTimeCounter > ioTimeCounter:
                    idleTimeCounter = durationTimeCounter - ioTimeCounter
                busyPercent = getBusyPercent(ioTimeCounter, idleTimeCounter)
                if None != busyPercent:
                    volume.set_metric("busy", busyPercent)

            if opsRead > 0:
                cacheReadHits = 99.0
                if (readHitIos / opsRead < 1):
                    cacheReadHits = readHitIos * 100.0 / opsRead
                volume.set_metric("cacheReadHits", cacheReadHits)

            if opsWrite > 0:
                cacheWriteHits = 99.0
                if (writeHitIos / opsWrite < 1):
                    cacheWriteHits = writeHitIos * 100.0 / opsWrite
                volume.set_metric("cacheWriteHits", cacheWriteHits)

            if opsTotal > 0:
                cacheHits = 99.0
                if (totalHitIos / opsTotal < 1):
                    cacheHits = totalHitIos * 100.0 / opsTotal
                volume.set_metric("cacheHits", cacheHits)


            blockSize = __getLongValueFrom("BlockSize", vStat)
            consumableBlocks = __getLongValueFrom("ConsumableBlocks", vStat)
            numberOfBlocks = __getLongValueFrom("NumberOfBlocks", vStat)
            logicalBytes = 0
            if consumableBlocks == 0:
                logicalBytes = numberOfBlocks * blockSize
            else:
                logicalBytes = consumableBlocks * blockSize
            size = long(logicalBytes / 1024 / 1024)
            volume.set_metric("totalSize", size)
            volume.set_metric("allocatedSize", size)

            # print("-------------------------size: ", size)
        except Exception,e:
            logger.error(traceback.format_exc())
    return None


def processDiskStats(array, diskStats, lastStats, _tracker, clockTickInterval):

    lastStatMap = {s['statID']: s for s in lastStats}

    for dStat in diskStats:
        try:
            statID = dStat.get('statID')
            if not lastStatMap.has_key(statID):
                continue
            lastStat = lastStatMap[statID]
            durationInt = __getDuration(dStat, lastStat)

            disk = array.get_physical_disk(statID)

            if not disk:
                logger.verbose("Discovered new Disk {}. "
                               "It will be reported on after the next inventory collection".format(statID))
                _tracker.request_inventory()
                continue

            state = str(convertCIMOperationalStatus(dStat.get("OperationalStatus")))
            disk.set_state(state)

            disk.set_metric("bytesRead",
                            __getStatValue('KBytesRead', dStat, lastStat, durationInt, 1024))
            disk.set_metric("bytesWrite",
                            __getStatValue('KBytesWritten', dStat, lastStat, durationInt, 1024))
            disk.set_metric("bytesTotal",
                            __getStatValue('KbytesTransferred', dStat, lastStat, durationInt, 1024))


            opsRead = __getStatValue('ReadIOs', dStat, lastStat, 1)
            opsWrite = __getStatValue('WriteIOs', dStat, lastStat, 1)
            opsTotal = __getStatValue('TotalIOs', dStat, lastStat, 1)
            readIOTimeCounter = __getStatValue('ReadIOTimeCounter', dStat, lastStat, 1)
            writeIOTimeCounter = __getStatValue('WriteIOTimeCounter', dStat, lastStat, 1)
            ioTimeCounter = __getStatValue('IOTimeCounter', dStat, lastStat, 1)
            idleTimeCounter = __getStatValue('IdleTimeCounter', dStat, lastStat, 1)

            disk.set_metric("opsRead", opsRead / durationInt)
            disk.set_metric("opsWrite", opsWrite / durationInt)
            disk.set_metric("opsTotal", opsTotal / durationInt)

            if None != clockTickInterval and clockTickInterval > 0:
                if readIOTimeCounter > 0 and opsRead > 0:
                    disk.set_metric("latencyRead", readIOTimeCounter / opsRead * clockTickInterval / 1000)
                if writeIOTimeCounter > 0 and opsWrite > 0:
                    disk.set_metric("latencyWrite", writeIOTimeCounter / opsWrite * clockTickInterval / 1000)
                if ioTimeCounter > 0 and opsTotal > 0:
                    disk.set_metric("latencyTotal", ioTimeCounter / opsTotal * clockTickInterval / 1000)

                durationTimeCounter = durationInt * 10^6 / clockTickInterval
                if (None == idleTimeCounter or 0 == idleTimeCounter) and durationTimeCounter > ioTimeCounter:
                    idleTimeCounter = durationTimeCounter - ioTimeCounter
                busyPercent = getBusyPercent(ioTimeCounter, idleTimeCounter)
                if None != busyPercent:
                    disk.set_metric("busy", busyPercent)

        except Exception, e:
            logger.error(traceback.format_exc())
    return None


def submit_performance(model, performance, _tracker, update):
    ps_array = performance['ps_array']

    last_stats_path = "{0}/raw_stats_{1}.txt".format(foglight.get_agent_specific_directory(), ps_array["SerialID"])
    last_stats = pickle_load(last_stats_path)

    logger.info("getArray {0} {1}", ps_array.get("SerialID"), ps_array.get("Vendor"))
    array = model.get_storage_array(ps_array.get("SerialID"), ps_array.get("Vendor"))

    if last_stats:
        controllerStats = performance['controllerStats']
        fcPortStats = performance['fcPortStats']
        iscsiPortStats = performance['iscsiPortStats']
        volumeStats = performance['volumeStats']
        diskStats = performance['diskStats']
        clockTickInterval = performance['clockTickInterval']

        processControllerStats(array, controllerStats, last_stats['controllerStats'], _tracker)
        processFcPortStats(array, fcPortStats,         last_stats['fcPortStats'],     _tracker, update)
        processIscsiPortStats(array, iscsiPortStats,   last_stats['iscsiPortStats'],  _tracker)
        processVolumeStats(array, volumeStats,         last_stats['volumeStats'],     _tracker, clockTickInterval)
        processDiskStats(array, diskStats,             last_stats['diskStats'],       _tracker, clockTickInterval)

    volume_mapping_spcs_path = "{0}/volume_mapping_spcs_{1}.txt".format(foglight.get_agent_specific_directory(), ps_array["SerialID"])
    volumeMappingSPCs = pickle_load(volume_mapping_spcs_path)
    processITLs(array, volumeMappingSPCs, update)

    pickle_dump(last_stats_path, performance)

    # print("controllerStats", controllerStats)
    return None


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


class PerfStates(object):
    Normal = 0
    Failed = 1  # also Offline (just not offline on switch port)
    Removed = 2
    New = 3
    Degraded = 4
    Rebuild = 5
    # struct modified for LUN, volume modified for Filer Volume.
    Modified = 6
    # Path Modified for VM hLD
    PathModified = 7
    Suspended = 8
    Maintenance = 9
    # vm instance moved @Deprecated
    vMotion = 10
    SwitchPortOffline = 11
    # 12, 13 are used by UI for different purpose
    ReadOnly = 14
    """
     We expected to receive information about this item, but did not. This may
     indicate removal/failure or it may just be a data collection failure. We
     just don't know.
    """
    NoInformation = 15

def convertCIMOperationalStatus(opStats):
    if None == opStats or 0 >= len(opStats):
        return PerfStates.Normal

    state = PerfStates.Normal

    for opStat in opStats:
        if None != opStat:
            if opStat in ("In Service"):
                if PerfStates.Normal == state:
                    state = PerfStates.Rebuild # disk rebuild states: "OK, In Service"
                else:
                    state = PerfStates.Degraded
                break
            elif opStat in ("Degraded", "Stressed", "Dormant", "Predictive Failure", "Rebooting",
                            "Write Disabled", "Write Protected", "Not Ready", "Power Saving Mode"):
                state = PerfStates.Degraded
                break
            elif opStat in ("Unknown", "Other", "Starting", "Completed", "Power Mode", "Online", "Success"):
                state = PerfStates.Normal
                break
            elif opStat in ("Removed"):
                state = PerfStates.Removed
                break
            elif opStat in ("Stopping", "Stopped"):
                state = PerfStates.Suspended
                break
            elif opStat in ("Supporting Entity in Error", "Non-Recoverable Error", "No Contact",
                            "Lost Communication", "Aborted", "Offline", "Failure"):
                state = PerfStates.Failed
                break
                """
                When there are multiple statuses, these won't cause the analysis
                to stop, e.g. disk status "OK, In Service"
                """
            elif opStat in ("OK", "DMTF Reserved", "Vendor Reserved"):
                state = PerfStates.Normal
            elif opStat in ("Error"):
                state = PerfStates.Failed
            else:
                state = PerfStates.Normal

    return state


def getBusyPercent(busyTicks, idleTicks):
    if None == busyTicks or None == idleTicks:
        return None

    totalTicks = busyTicks + idleTicks
    if totalTicks == 0:
        return None

    return busyTicks * 100 / totalTicks


def computeUtilization(bytesTransferred, speedBytesPerSecond, seconds):
    if bytesTransferred == None or speedBytesPerSecond == None or seconds == None:
        return None

    if seconds == 0 or speedBytesPerSecond == 0:
        return None

    # Bandwidth is the total number of bytes we could have transferred during this time period.
    total_bandwidth = speedBytesPerSecond * seconds

    # Utilization is how many we transferred divided by how many we could have.
    utilization = bytesTransferred * seconds / total_bandwidth * 100

    return utilization


def __getLongValueFrom(metricName, cimobj):
    v = 0
    if cimobj.has_key(metricName) and None != cimobj.get(metricName):
        v = long(cimobj.get(metricName) or 0)
    return v



def __getStatValue(metricName, stat, lastStat, duration, multiplier=1):
    v = 0

    if stat.has_key(metricName) and lastStat.has_key(metricName):
        currVal = stat[metricName]
        lastVal = lastStat[metricName]

        if currVal != None and lastVal != None:
            v = (currVal - lastVal) * multiplier / duration
            # print(metricName, v)
    return v


def __getDuration(stat, lastStat):
    durationInt = 1
    if None != stat and lastStat != None:
        st1 = stat.get("StatisticTime")
        st0 = lastStat.get("StatisticTime")

        if st1.is_interval:
            d1 = st1.timedelta
            d0 = st0.timedelta
        else:
            d1 = st1.datetime
            d0 = st0.datetime


        if None != d1 and None != d0:
            durationInt = (d1 - d0).seconds
        else:
            durationInt = 300
    #TODO collection interval

    # print('durationInt: ', durationInt)
    return durationInt