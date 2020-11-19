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
from smis_asp import SanASP

# Set up a logger for this Agent.
logger = foglight.logging.get_logger("smis-agent")
asp = SanASP()

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
        controller_name = c["Name"]
        if c.has_key("ElementName"):
            controller_name = c["ElementName"]

        controller = array.get_controller(controller_name.upper())

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
            if wwn is None: continue

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

        wwn = p.get("Name")
        if wwn is None:
            logger.warn("ISCSI Port name is None")
            continue

        comma = wwn.find(',')
        if 0 < comma:
            wwn = wwn[0:comma]

        port = array.get_port("ISCSI", wwn)
        if p.get("ElementName") is not None:
            port.set_property("name", p.get("ElementName"))
        else:
            port.set_property("name", p.get("Name"))

        if p.has_key("iqn"):
            port.set_property("alias", p.get("iqn"))

        controller_name = p.get("ControllerName")
        if controller_name is not None:
            controller = array.get_controller(controller_name.upper())
            port.associate_with(controller)

        # logger.debug("ISCSI port ", p.get("name") )
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
            # print(v.tomof())

            lun = array.get_lun(v["DeviceID"])

            lun.set_label("Lun")   # so the UI knows to call these "Volumes"
            _name = ''
            if v.has_key("Caption") and v["Caption"] is not None:
                _name = v["Caption"]
            if v.has_key("ElementName") and v["ElementName"] is not None:
                _name = v["ElementName"]
            lun.set_property("name", _name)

            pool = poolsMap[v["PoolID"]]
            lun.associate_with(pool)

            isThinProvisioned = False
            if (v.has_key("ThinlyProvisioned")):
                isThinProvisioned = str(v["ThinlyProvisioned"])
                lun.set_property("isThinProvisioned", isThinProvisioned == 'True')

            blockSize = 0 if not v.has_key("BlockSize") else v["BlockSize"]
            consumableBlocks = v["ConsumableBlocks"]
            numberOfBlocks = v["NumberOfBlocks"]
            logicalBytes = 0
            if consumableBlocks == 0:
                logicalBytes = numberOfBlocks * blockSize
            else:
                logicalBytes = consumableBlocks * blockSize
            size = logicalBytes / 1024 / 1024
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
                if 0 < consumedBytes:
                    lun.set_property("advertisedSize", long(consumedBytes / 1024 / 1024))

            # logger.debug("lun.advertisedSize : {0} lun.size : {1}",
            #              lun.get_property("advertisedSize"), lun.get_property("size"))

            rule = None
            if rule is None and v.has_key("RaidLevel"):
                rule = v["RaidLevel"]
            if rule is None and v.has_key("ErrorMethodology"):
                rule = v["ErrorMethodology"]

            protection = getProtection(rule)
            lun.set_property("protection", protection)

            # logger.debug("Lun {0} protection: {1}", v["DeviceID"], protection)
            # RawCapacity
        except Exception, e:
            logger.error(e.message)
    logger.info("processVolumes end")
    return None


def getProtection(rule):
    result = rule
    if result is None:
        result = "(unknown)"
    return result
'''
    if rule in ('RAID0'):
        result += " S"
    elif rule in ('RAID1', 'RAID10', 'RAID1+0'):
        result += " M/S"
    elif rule in ('RAID3', 'RAID5', 'RAID6', 'RAID50', 'RAID60'):
        result += " S/P"
    elif rule in ('RAID51', 'RAID15'):
        result += " M/S/P"
'''



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


def processITLs(array, ps_array, cim_volumeMappingSPCs, volumeStats):
    itl0s = {}
    itl1s = {}
    is_unity = False
    if ps_array.get("Product") is not None:
        is_unity = ps_array.get("Product").startswith("Unity")

    if None == cim_volumeMappingSPCs:
        logger.warn('There''s no ITLs found!')
        return
    # print("len(volumePath):", len(cim_volumeMappingSPCs.keys()))

    if len(volumeStats) == 0:
        return
    volumeDeviceIdUUIdMap = {}
    for vs in volumeStats:
        # print(vs['statID'], vs['uuid'])
        volumeDeviceIdUUIdMap[vs['statID']] = vs['uuid']

    for volumePath in cim_volumeMappingSPCs.keys():
        spcs = cim_volumeMappingSPCs[volumePath]

        for spc in spcs:
            pcfus = spc.get("pcfus")
            ports = spc.get("ports")
            storHardwareIDs = spc.get("storHardwareIDs")

            portsLen = 0 if None == ports else len(ports)
            pcfusLen = 0 if None == pcfus else len(pcfus)
            hardwareIdsLen = 0 if None == storHardwareIDs else len(storHardwareIDs)

            if pcfusLen == 0 or portsLen == 0: continue

            # logger.debug("get mapping to LUN {0}, pcfus: {1}, ports: {2}, storHardwareIDs: {3}",
            #              volumePath, pcfusLen, portsLen, hardwareIdsLen)

            for pcfu in pcfus:
                deviceNumber = long(pcfu.get("DeviceNumber"), 16)
                if is_unity: deviceNumber = long(pcfu.get("DeviceNumber"))

                volumePath = pcfu.path.get("Dependent")
                lunId = volumePath.get("DeviceID")

                for port in ports:
                    portwwn = port.get("PermanentAddress").lower()
                    portType = 'FC' if "fcport" in port.get("CreationClassName").lower() else "ISCSI"


                    itl0_devicePath = None
                    if volumeDeviceIdUUIdMap.has_key(lunId):
                        itl0_devicePath = volumeDeviceIdUUIdMap[lunId]
                    # logger.debug("get ITL0 lunId: {0}, devicePath: {1}", lunId, itl0_devicePath)

                    itl0Key = itl0_devicePath
                    if not itl0s.__contains__(itl0Key):
                        itl0 = {
                            'lun': lunId,
                            'devicePath': itl0_devicePath,
                        }
                        itl0s[itl0Key] = itl0

                    if hardwareIdsLen == 0:
                        continue
                    # targetPortKey = foglight.topology.make_object_key(portType, {"wwn": portwwn})
                    # if array._getObject(targetPortKey) is None:
                    #     logger.warn("Found no port {0}", portwwn)
                    #     continue
                    for hardwareId in storHardwareIDs:
                        if hardwareId.get("StorageID") is None: continue
                        storageId = hardwareId.get("StorageID").lower()
                        devicePath = "%s\t%s:%s" % (storageId, portwwn, deviceNumber)

                        # logger.debug("get ITL1 lunId: {0}, portwwn: {1}， devicePath: {2}",
                        #              lunId, portwwn, devicePath)

                        itl1Key = lunId +devicePath
                        if not itl1s.__contains__(itl1Key):
                            itl1 = {
                                'lun': lunId,
                                'targetPort': portwwn,
                                'targetPortType': portType,
                                'devicePath': devicePath
                            }
                            itl1s[itl1Key] = itl1


    itl1s = sorted(itl1s.values(), key=lambda d : d['devicePath'])

    itl1paths = ArrayList()
    itl0paths = ArrayList()
    for itl1 in itl1s:
        itl1path = array.create_ITL1(itl1['devicePath'], itl1['lun'], itl1['targetPort'], itl1['targetPortType'])
        if itl1path is not None:
            itl1paths.add(itl1path)

    for itl0 in itl0s.values():
        itl0path = array.create_ITL0(itl0['devicePath'], itl0['lun'])
        if itl0path is not None:
            itl0paths.add(itl0path)

    array.set_ITLs0(itl0paths)
    array.set_ITLs1(itl1paths)

    logger.info('itl1s:%d' % len(itl1paths))
    logger.info('itl0s:%d' % len(itl0paths))

    return None


def submit_inventory(sanNasModel, inventory):
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

    volume_mapping_spcs_path = get_volume_mapping_spcs_path(cim_array["SerialID"])
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
                controller.set_metric("latencyTotalBlock", ioTimeCounter * 1.0 / opsTotal)
            # logger.debug("latencyTotalBlock: {0}", ioTimeCounter * 1.0 / opsTotal)

            state = str(convertCIMOperationalStatus(cStat.get("OperationalStatus")))
            controller.set_state(state)

            # busyTicks = long(cStat.get("IOTimeCounter"))
        except Exception,e:
            logger.error(traceback.format_exc())
    return None


def processFcPortStats(array, fcPortStats, lastStats, _tracker):
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
            maxSpeed = 0
            if pStat.get("MaxSpeed") is not None:
                maxSpeed= pStat.get("MaxSpeed") / 1024 / 1024

            # logger.debug("currentSpeedMb:{0}", pStat.get("Speed"))
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

            state = str(convertCIMOperationalStatus(pStat.get("OperationalStatus")))
            port.set_state(state)

            bytesRead = __getStatValue('KBytesRead', pStat, lastStat, durationInt, 1024)
            bytesWrite = __getStatValue('KBytesWritten', pStat, lastStat, durationInt, 1024)
            bytesTotal = __getStatValue('KbytesTransferred', pStat, lastStat, durationInt, 1024)

            port.set_metric("bytesRead", bytesRead)
            port.set_metric("bytesWrite", bytesWrite)
            port.set_metric("bytesTotal", bytesTotal)

            # currentSpeed = pStat.get("Speed") / 1024 / 1024
            # maxSpeed = pStat.get("MaxSpeed") / 1024 / 1024
            #
            # port.set_metric("currentSpeedMb", currentSpeed)
            # port.set_metric("maxSpeedMb", maxSpeed)
            #
            # port.set_metric("bytesReadUtilization",
            #                 computeUtilization(bytesRead, currentSpeed, durationInt))
            # port.set_metric("bytesWriteUtilization",
            #                 computeUtilization(bytesWrite, currentSpeed, durationInt))

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
    _product = array.get_property("Product")

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

            if _product != 'PURESTORAGE_ArrayProduct':
                state = str(convertCIMHealthState(vStat.get("HealthState")))
            else:
                state = str(convertCIMOperationalStatus(vStat.get("OperationalStatus")))
            volume.set_state(state)

            if state != "0":
                logger.info("the state of lun {0} is {1}", volume.get_property("name"), state)

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
            writeHitIos = __getStatValue('WriteHitIOs', vStat, lastStat, 1)
            totalHitIos = readHitIos + writeHitIos

            readIOTimeCounter = __getStatValue('ReadIOTimeCounter', vStat, lastStat, 1)
            writeIOTimeCounter = __getStatValue('WriteIOTimeCounter', vStat, lastStat, 1)
            ioTimeCounter = __getStatValue('IOTimeCounter', vStat, lastStat, 1)
            idleTimeCounter = __getStatValue('IdleTimeCounter', vStat, lastStat, 1)

            volume.set_metric("opsRead", opsRead / durationInt)
            volume.set_metric("opsWrite", opsWrite / durationInt)
            volume.set_metric("opsTotal", opsTotal / durationInt)

            latency_read_hits = __getStatValue("ReadHitLatencyTime_ms", vStat, lastStat, 1)
            latency_read_misses = __getStatValue("ReadMissLatencyTime_ms", vStat, lastStat, 1)
            latency_read = latency_read_hits + latency_read_misses
            latency_write = __getStatValue("WriteLatencyTime_ms", vStat, lastStat, 1)
            latency_total = latency_read + latency_write
            volume.set_metric("latencyWrite", latency_write)
            volume.set_metric("latencyRead", latency_read)
            volume.set_metric("latencyTotal", latency_total)

            if None != clockTickInterval and clockTickInterval > 0:
                clock_in_millisecond = 1
                if clockTickInterval > 1000000:
                    clock_in_millisecond = 1
                else:
                    clock_in_millisecond = clockTickInterval / 1000

                if readIOTimeCounter > 0 and opsRead > 0:
                    latency_read = (readIOTimeCounter * 1.0 / opsRead) * clock_in_millisecond
                    volume.set_metric("latencyRead", latency_read)
                if writeIOTimeCounter > 0 and opsWrite > 0:
                    latency_write = (writeIOTimeCounter * 1.0 / opsWrite) * clock_in_millisecond
                    volume.set_metric("latencyWrite", latency_write)
                if ioTimeCounter > 0 and opsTotal > 0:
                    latency_total = (ioTimeCounter * 1.0 / opsTotal) * clock_in_millisecond
                    volume.set_metric("latencyTotal", latency_total)

                durationTimeCounter = durationInt * 1000000
                if (None == idleTimeCounter or 0 == idleTimeCounter) and durationTimeCounter > ioTimeCounter:
                    idleTimeCounter = durationTimeCounter - ioTimeCounter
                busyPercent = getBusyPercent(ioTimeCounter, abs(idleTimeCounter))
                # if ioTimeCounter != 0:
                #     logger.debug("ioTimeCounter:{0}, idleTimeCount:{1}, busyPercent:{2}, durationTimeCounter:{3}", ioTimeCounter, idleTimeCounter, busyPercent, durationTimeCounter)
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

            latency_read = __getStatValue("ReadLatencyTime_ms", dStat, lastStat, 1)
            latency_write = __getStatValue("WriteLatencyTime_ms", dStat, lastStat, 1)
            latency_total = latency_read + latency_write
            disk.set_metric("latencyWrite", latency_write)
            disk.set_metric("latencyRead", latency_read)
            disk.set_metric("latencyTotal", latency_total)

            if None != clockTickInterval and clockTickInterval > 0:
                clock_in_millisecond = 1
                if clockTickInterval > 1000000:
                    clock_in_millisecond = 1
                elif clockTickInterval > 1000:
                    clock_in_millisecond = clockTickInterval / 1000

                if readIOTimeCounter > 0 and opsRead > 0:
                    latency_read = (readIOTimeCounter * 1.0 / opsRead) * clock_in_millisecond
                    disk.set_metric("latencyRead", latency_read)
                if writeIOTimeCounter > 0 and opsWrite > 0:
                    latency_write = (writeIOTimeCounter * 1.0 / opsWrite) * clock_in_millisecond
                    disk.set_metric("latencyWrite", latency_write)
                if ioTimeCounter > 0 and opsTotal > 0:
                    latency_total = (ioTimeCounter * 1.0 / opsTotal) * clock_in_millisecond
                    disk.set_metric("latencyTotal", latency_total)

                # logger.debug("disk {0} latencyRead: {1} {2} {3}", statID, latency_read, readIOTimeCounter, opsRead)
                # logger.debug("disk {0} latency_write: {1} {2} {3}", statID, latency_write, writeIOTimeCounter, opsWrite)
                # logger.debug("disk {0} latencyTotal: {1}", statID, latency_total))

                if dStat.has_key("DiskIdleTimeCounter") and dStat.has_key("DiskElapsedTimeCounter"): #huawei
                    diskIdleTimeCounter = __getStatValue('DiskIdleTimeCounter', dStat, lastStat, 1)
                    diskElapsedTimeCounter = __getStatValue('DiskElapsedTimeCounter', dStat, lastStat, 1)
                    busy_percent = (diskElapsedTimeCounter - diskIdleTimeCounter) * 100.0 / diskElapsedTimeCounter
                else:
                    durationTimeCounter = durationInt * 1000000
                    if (None == idleTimeCounter or 0 == idleTimeCounter) and durationTimeCounter > ioTimeCounter:
                        idleTimeCounter = durationTimeCounter - ioTimeCounter
                    busy_percent = getBusyPercent(ioTimeCounter, abs(idleTimeCounter))
                if None != busy_percent:
                    disk.set_metric("busy", busy_percent)

        except Exception, e:
            logger.error(traceback.format_exc())
    return None


def processPoolStats(array, poolVolumeMap, cim_pools):
    for poolID in poolVolumeMap.keys():
        pool = array.get_pool(poolID)
        cim_luns = poolVolumeMap[poolID]

        advertisedSize = 0
        for v in cim_luns:
            lun = array.get_lun(v["DeviceID"])
            advertisedSize += lun.get_property("advertisedSize")

        pool.set_metric("conf_LunSize", advertisedSize)

        cim_pool = findPoolByID(cim_pools, poolID)
        logger.debug("pool: {0} ", cim_pool.tomof())

        total_space = 0
        if total_space is None or 0 == total_space:
            total_space = cim_pool.get("TotalManagedSpace")
        pool.set_metric("conf_capacity", total_space >> 20)

        consumed = cim_pool.get("CurrentSpaceConsumed")
        remaining_space = None
        if consumed is not None and cim_pool.classname.startswith('TPD'):
            used_admin_space = cim_pool.get("UsedSnapAdminSpace")
            if used_admin_space is not None:
                consumed = consumed + used_admin_space
            remaining_space= total_space - consumed
        else:
            remaining_space = cim_pool.get("RemainingManagedSpace")

        if None != remaining_space:
            pool.set_metric("conf_available", remaining_space >> 20)
            pool.set_metric("raw_available", remaining_space >> 20)

        # state = str(convertCIMOperationalStatus(cim_pool.get("OperationalStatus")))
        # pool.set_state(state)

    return None

def findPoolByID(pools, poolID):
    for p in pools:
        if poolID == p.get("InstanceID"):
            return p
    return None

def submit_performance(model, performance, _tracker):
    ps_array = performance['ps_array']

    last_stats_path = get_array_stats_path(ps_array["SerialID"])
    last_stats = pickle_load(last_stats_path)

    logger.info("getArray {0} {1}", ps_array.get("SerialID"), ps_array.get("Vendor"))
    array = model.get_storage_array(ps_array.get("SerialID"), ps_array.get("Vendor"))

    controllerStats = performance['controllerStats']
    fcPortStats = performance['fcPortStats']
    iscsiPortStats = performance['iscsiPortStats']
    volumeStats = performance['volumeStats']
    diskStats = performance['diskStats']
    clockTickInterval = performance['clockTickInterval']
    poolVolumeMap = performance['poolVolumeMap']
    pools = performance['pools']

    if last_stats:
        processControllerStats(array, controllerStats, last_stats['controllerStats'], _tracker)
        processFcPortStats(array, fcPortStats,         last_stats['fcPortStats'],     _tracker)
        processIscsiPortStats(array, iscsiPortStats,   last_stats['iscsiPortStats'],  _tracker)
        processVolumeStats(array, volumeStats,         last_stats['volumeStats'],     _tracker, clockTickInterval)
        processDiskStats(array, diskStats,             last_stats['diskStats'],       _tracker, clockTickInterval)
        processPoolStats(array, poolVolumeMap, pools)

    volume_mapping_spcs_path = get_volume_mapping_spcs_path(ps_array["SerialID"])
    volumeMappingSPCs = pickle_load(volume_mapping_spcs_path)
    processITLs(array, ps_array, volumeMappingSPCs, volumeStats)

    pickle_dump(last_stats_path, performance)

    # print("controllerStats", controllerStats)
    return None


def get_volume_mapping_spcs_path(array_id):
    volume_mapping_spcs_path = "{0}/volume_mapping_spcs_{1}.txt".format(
        foglight.get_agent_specific_directory(), array_id)
    return volume_mapping_spcs_path

def get_array_stats_path(array_id):
    array_stats_path = "{0}/raw_stats_{1}.txt".format(foglight.get_agent_specific_directory(), array_id)
    return array_stats_path

def get_cim_array_path(array_name):
    cim_array_path = "{0}/cim_array_{1}.txt".format(foglight.get_agent_specific_directory(), array_name)
    return cim_array_path


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


def convertCIMHealthState(healthState):
    state = PerfStates.Normal
    if healthState is None:
        return state
    if healthState == 0:
        PerfStates.NoInformation
    elif healthState == 5:
        state = PerfStates.Normal
    else:
        state = PerfStates.Failed
    return state

def convertCIMOperationalStatus(opStats):
    if None == opStats or 0 >= len(opStats):
        return PerfStates.Normal

    state = PerfStates.Normal

    for opStat in opStats:
        if None != opStat:
            """
            When there are multiple statuses, these won't cause the analysis
            to stop, e.g. disk status "OK, In Service"
            """
            if opStat in "In Service":
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
            elif opStat in "Removed":
                state = PerfStates.Removed
                break
            elif opStat in ("Stopping", "Stopped"):
                state = PerfStates.Suspended
                break
            elif opStat in ("Supporting Entity in Error", "Non-Recoverable Error", "No Contact",
                            "Lost Communication", "Aborted", "Offline", "Failure"):
                state = PerfStates.Failed
                break
            elif opStat in ("OK", "DMTF Reserved", "Vendor Reserved"):
                state = PerfStates.Normal
                break
            elif opStat in "Error":
                state = PerfStates.Failed
                break
            else:
                state = PerfStates.Normal
                break

    return state


def getBusyPercent(busyTicks, idleTicks):
    if busyTicks is None or idleTicks is None:
        return None

    totalTicks = busyTicks + idleTicks
    if totalTicks == 0:
        return None

    return busyTicks * 100 / totalTicks


def computeUtilization(bytesTransferred, speedBytesPerSecond, seconds):
    if bytesTransferred is None or speedBytesPerSecond is None or seconds is None:
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

        if duration == 0:
            duration = 1
        if currVal != None and lastVal != None:
            v = (currVal - lastVal) * multiplier / duration
            # print(metricName, v)
    return v

def __str2datetime(str):
    si = str.index('.')
    if si > 0:
        s = str[0:si]
        return datetime.datetime.strptime(s, '%Y%m%d%H%M%S')
    else:
        return None

def __getDuration(stat, lastStat):
    durationInt = asp.performance_frequency.seconds
    if stat is not None and lastStat is not None:
        st1 = stat.get("StatisticTime")
        st0 = lastStat.get("StatisticTime")

        if st1 is None or st0 is None:
            return durationInt

        if isinstance(st1, basestring):
            d1 = __str2datetime(st1)
            d0 = __str2datetime(st0)
        elif st1.is_interval:
            d1 = st1.timedelta
            d0 = st0.timedelta
        else:
            d1 = st1.datetime
            d0 = st0.datetime


        if None != d1 and None != d0:
            durationInt = (d1 - d0).seconds

        if durationInt == 0:
            durationInt = asp.performance_frequency.seconds
    #TODO collection interval

    # print('durationInt: ', durationInt)
    return durationInt