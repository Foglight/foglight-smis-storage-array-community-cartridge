# coding=utf-8
from __future__ import print_function

import string
import traceback
import foglight.logging
from smisconn import smisconn

from pywbemReq.cim_obj import CIMInstanceName, CIMInstance, tocimobj
from pywbemReq.cim_operations import is_subclass
from pywbemReq.cim_types import *

from urllib3.exceptions import SSLError as _SSLError

logger = foglight.logging.get_logger("smisutil")

def getRegisteredProfiles(_conn):
    kProfilePropList = ["InstanceID", "RegisteredVersion", "RegisteredName"]
    profiles = _conn.EnumerateInstances("CIM_RegisteredProfile", DeepInheritance=True, PropertyList=kProfilePropList)
    return profiles

def getElementsForProfile(conn, profileName):
    _conn = smisconn(conn)
    profiles = getRegisteredProfiles(_conn)
    profiles = [p for p in profiles if p.get("RegisteredName") == profileName]
    profiles = profiles[:1]
    logger.info('profiles: %d' % len(profiles))

    elements = []
    for p in profiles:
        managedElements = _conn.Associators(p.path,
                                AssocClass="CIM_ElementConformsToProfile",
                                Role="ConformantStandard",
                                ResultRole="ManagedElement")
        for managedElement in managedElements:
            if managedElement.get("ElementName") is None or managedElement.get("ElementName") == "":
                logger.debug("managedElement: {0}", managedElement.tomof())
                if managedElement.get("Name") is not None and managedElement.get("Name") != "":
                    managedElement.__setitem__("ElementName", managedElement.get("Name"))
                elif managedElement.get("RegisteredName") is not None and managedElement.get("RegisteredName") != "":
                    managedElement.__setitem__("ElementName", managedElement.get("RegisteredName"))
            elements.append(managedElement)
    return elements

def getArray(conn):
    managedElements = getElementsForProfile(conn, "Array")
    logger.info("managedElements: %d" % len(managedElements))
    ps_array = managedElements[0]
    getProductInfo(conn, ps_array)
    return ps_array


def getArrays(conn):
    managedElements = getElementsForProfile(conn, "Array")
    logger.info('managedElements: %d' % len(managedElements))

    arrays = []
    _operationalStatusValues = None
    for m in managedElements:
        if not is_subclass(conn, m.path.namespace, "CIM_ComputerSystem", m.classname):
            logger.info('Array skipped because it is not a CIM_ComputerSystem')
            continue

        logger.info('Dedicated: %s' % m.get('Dedicated'))
        if not {15}.issubset(m.get('Dedicated')):
            logger.info('Array skipped because it is not a block storage system')
            continue

        if not getProductInfo(conn, m):
            logger.info('Array skipped because no vendor and/or model information found')
            unknown = "Unknown"
            m.__setitem__("Model", unknown)
            m.__setitem__("Vendor", unknown)
            m.__setitem__("Product", unknown)
            m.__setitem__("SerialID", unknown)
            m.__setitem__("Version", unknown)
            # continue

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, m, m.classname)
        status = convertOperationalStatusValues(m['OperationalStatus'], _operationalStatusValues)
        m.__setitem__("OperationalStatus", status)

        arrays.append(m)
    return arrays


def getProductInfo(conn, ps_array):
    _conn = smisconn(conn)
    physpacks = _conn.Associators(ps_array.path,
                                AssocClass="CIM_SystemPackaging",
                                ResultClass="CIM_PhysicalPackage")
    if physpacks is None:
        logger.warn('No Chassis information found for ComputerSystem {0}', ps_array.get("Name"))
        return False

    use_chassis = None
    if len(physpacks) == 1:
        use_chassis = physpacks[0]
    else:
        logger.info('More than one Chassis associated with ComputerSystem {0}', ps_array.get("Name"))
        for p in physpacks:
            if p.get("ChassisPackageType") in ("17", "22"):
                use_chassis = p
                break
        if use_chassis is None and len(physpacks)>0:
            logger.warn('Valid chassis type not found, using index 0')
            use_chassis = physpacks[0]

    products = _conn.Associators(use_chassis.path,
                                AssocClass="CIM_ProductPhysicalComponent",
                                ResultClass="CIM_Product")
    if products is None or len(products) == 0:
        for p in physpacks:
            products = _conn.Associators(use_chassis.path,
                                         AssocClass="CIM_ProductPhysicalComponent",
                                         ResultClass="CIM_Product")
            if products is not None and len(products) > 0:
                break
        if products is None or len(products) == 0:
            logger.warn('No Product information found for ComputerSystem {0}', ps_array.get("Name"))
            return False

    model = use_chassis.get("Model")
    if model is not None:
        model = string.replace(model, "Rack Mounted ", "")
        model = string.replace(model, '_', '-')
        ps_array.__setitem__("Model", model)
    else:
        logger.warn('Model not found for ComputerSystem {0}', ps_array.get("Name"))


    product = products[0]
    vendor = product.get("Vendor")
    if vendor is None:
        logger.warn('Vendor not found for ComputerSystem {0}', ps_array.get("Name"))
    else:
        ps_array.__setitem__("Vendor", vendor)

    ps_array.__setitem__("Product", product.get("Name"))
    ps_array.__setitem__("SerialID", product.get("IdentifyingNumber"))
    ps_array.__setitem__("Version", product.get("Version"))

    return True

def getViewCapabilities(conn, ps_array):
    _conn = smisconn(conn)
    viewCaps = _conn.Associators(ps_array.path,
                                AssocClass="CIM_ElementCapabilities",
                                ResultClass="SNIA_ViewCapabilities")
    return viewCaps


def getSupportedViews(conn, ps_array, isBlockStorageViewsSupported):
    supportedViews = []
    viewCaps = []
    if isBlockStorageViewsSupported:
        viewCaps = getViewCapabilities(conn, ps_array)
    if len(viewCaps) > 0:
        supportedViews = viewCaps[0].get("SupportedViews")

    logger.info("supportedViews: {0}", supportedViews)
    return supportedViews


def getOperationalStatusValues(conn, ps_array, className):
    _conn = smisconn(conn)
    cls = _conn.GetClass(className,
                        namespace=ps_array.path.namespace,
                        LocalOnly=False,
                        IncludeQualifiers=True,
                        IncludeClassOrigin=True,
                        PropertyList=['OperationalStatus'])
    ops = cls.properties.get("OperationalStatus")
    if ops.qualifiers.has_key('Values'):
        return ops.qualifiers['Values'].value
    else:
        return []


def convertOperationalStatusValues(operationalStatus, operationalStatusValues):
    values = []
    for status in operationalStatus:
        if len(operationalStatusValues) > status:
            values.append(operationalStatusValues[status])
        else:
            values.append("OK")
    return values


def getControllers(conn, ps_array):
    controllers = []
    _conn = smisconn(conn)
    comps = _conn.Associators(ps_array.path,
                                AssocClass="CIM_ComponentCS",
                                ResultClass="CIM_ComputerSystem",
                                Role="GroupComponent",
                                ResultRole="PartComponent")

    arrayClassName = ps_array.classname
    _operationalStatusValues = None
    for c in comps:

        # EMC Clariion and Symmetrix have front-end FC ports on EMC_StorageProcessorSystem Class
        if ((arrayClassName.startswith("Clar") or arrayClassName.startswith("Symm"))
                and not c.classname.__contains__("StorageProcessorSystem")):
            continue
        if c.classname.lower().__contains__("nodepairsystem"):
            continue
        if arrayClassName.startswith("Nex_") and not c.classname.__contains__("StorageControllerSystem"):
            continue

        if c.classname.startswith("HPEVA"):
            c.path.__delitem__("Name")
            c.path.__setitem__("ElementName", c.get("ElementName"))


        software_identities = _conn.Associators(c.path, AssocClass="CIM_InstalledSoftwareIdentity",
                                               ResultClass="CIM_SoftwareIdentity");
        if software_identities is not None and len(software_identities) > 0 and software_identities[0] is not None:
            versionString = software_identities[0].get("VersionString")
            c.__setitem__("VersionString", versionString)

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, c.classname)
        if c.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(c['OperationalStatus'], _operationalStatusValues)
            c.__setitem__("OperationalStatus", status)

        controllers.append(c)
        # print(c.tocimxml().toxml())
    logger.info("controllers: {0}", len(controllers))
    return controllers


def getFcPorts(conn, ps_array, controllers):
    _conn = smisconn(conn)
    fc_ports = []
    if len(controllers) <= 0:
        return fc_ports

    empty_controllers= []
    for ct in controllers:
        try:
            ports = _conn.Associators(ct.path, AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort",
                                    Role="GroupComponent",
                                    ResultRole="PartComponent")

            if ports is None or  len(ports) <= 0:
                logger.warn("No FC ports found for %s using %s" % (ct.get("ElementName"),  conn) )
                empty_controllers.append(ct);
            else:
                for p in ports:
                    p.__setitem__("ControllerName", ct.get("ElementName"))
                fc_ports += ports
        except Exception as err:
            logger.error("getFcPorts Error: %s" % err.message)
    # for x in empty_controllers:
    #     controllers.remove(x)

    if len(fc_ports) <= 0 and len(controllers) > 0:
        fc_ports = _conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort")
        for p in fc_ports:
            p.__setitem__("ControllerName", controllers[0].get("ElementName"))

    if len(fc_ports) <= 0 and len(controllers) > 0:
        fc_ports = _conn.EnumerateInstances("CIM_FCPort", namespace=ps_array.path.namespace)
        for p in fc_ports:
            p.__setitem__("ControllerName", p["SystemName"])

    ports = []
    _operationalStatusValues = None
    for p in fc_ports:
        # don't include back-end ports
        usageRestriction = p.get("UsageRestriction")
        if 3 == usageRestriction:
            continue

        if p.classname.startswith("HPEVA"):
            p.path.__delitem__("SystemName")
            p.path.__delitem__("DeviceID")
            p.path.__setitem__("Name", p.get("Name"))

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, p.classname)
        if p.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(p['OperationalStatus'], _operationalStatusValues)
            p.__setitem__("OperationalStatus", status)

        ports.append(p)

    logger.info("fc ports: {0}", len(ports))
    return ports


def get_ip_ports(conn, ps_array, controllers):
    _conn = smisconn(conn)
    iscsi_ports = []
    if len(controllers) <= 0:
        return iscsi_ports

    port_map = {}
    endpoint_map = {}
    endpoint_port_map = {}
    ports = []
    endpoints = []
    try:
        for ct in controllers:
            ports = _conn.Associators(ct.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_EthernetPort")
            if ports:
                for p in ports:
                    port_map[p.path.get("DeviceID")] = p

        ads = _conn.EnumerateInstances("CIM_DeviceSAPImplementation", namespace=ps_array.path.namespace)
        for ad in ads:
            endpoint_port_map[ad.get("Dependent").get("Name")] = ad.get("Antecedent")
            # endpoint_port_map[ad.get("Antecedent").get("DeviceID")] = ad.get("Dependent")
            # logger.debug("endpoint path {0}", ad.get("Dependent"))

        _operationalStatusValues = getOperationalStatusValues(conn, ps_array, ports[0].classname)

        for ct in controllers:
            endpoints = _conn.Associators(ct.path,
                                    AssocClass="CIM_HostedAccessPoint",
                                    ResultClass="CIM_iSCSIProtocolEndpoint")
            if endpoints:
                for ep in endpoints:
                    # logger.debug(ep.path.get("Name"))
                    port_path = endpoint_port_map[ep.path.get("Name")]
                    if port_path is None: continue
                    port = port_map[port_path.get("DeviceID")]
                    if port.has_key("OperationalStatus"):
                        status = convertOperationalStatusValues(port['OperationalStatus'], _operationalStatusValues)
                        port.__setitem__("OperationalStatus", status)
                    port.__setitem__("iqn", ep.path.get("Name"))
                    port.__setitem__("ControllerName", ct.get("ElementName"))
                    port.__setitem__("Name", port.get("PermanentAddress"))
                    # port.__setitem__("Name", port.get("DeviceID"))
                    # logger.debug("endpoint {0}", ep.tomof())
                    iscsi_ports.append(port)

    except Exception as err:
        logger.error("getIscisiPorts Error: %s" % err.message)

    logger.info("iscsi ports: {0}", len(iscsi_ports))
    return iscsi_ports


def getIscisiPorts(conn, ps_array, controllers):
    _conn = smisconn(conn)
    iscsi_ports = []
    if len(controllers) <= 0:
        return iscsi_ports

    try:
        for ct in controllers:
            ports = _conn.Associators(ct.path,
                                    AssocClass="CIM_HostedAccessPoint",
                                    ResultClass="CIM_iSCSIProtocolEndpoint")
            if ports:
                for p in ports:
                    p.__setitem__("ControllerName", ct.get("ElementName"))
                iscsi_ports += ports
    except Exception as err:
        logger.error("getIscisiPorts Error: %s" % err.message)

    if len(iscsi_ports) <= 0:
        iscsi_ports = _conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_iSCSIProtocolEndpoint")

        for p in iscsi_ports:
            p.__setitem__("ControllerName", controllers[0].get("ElementName"))

    _operationalStatusValues = None
    for p in iscsi_ports:
        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, p.classname)
        if p.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(p['OperationalStatus'], _operationalStatusValues)
            p.__setitem__("OperationalStatus", status)

    logger.info("iscsi ports: {0}", len(iscsi_ports))
    return iscsi_ports


def getExtents(conn, ps_array, controllers):
    _conn = smisconn(conn)
    extents = []
    try:
        extents = _conn.Associators(ps_array.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_StorageExtent")
    except Exception as err:
        logger.error("Failed to get extents by array %s %s" % (ps_array.path, err.message))

    if len(extents) == 0:
        for ct in controllers:
            extentComps = _conn.Associators(ct.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_StorageExtent")
            extents += extentComps

    extentLookup = {}
    for extent in extents:
        if extent.has_key("DeviceID"):
            extentLookup[extent.get("DeviceID")] = extent
    logger.info("extents: {0}", len(extentLookup))
    return extentLookup


def getPools(conn, ps_array):
    _conn = smisconn(conn)
    spools = _conn.Associators(ps_array.path,
                                AssocClass="CIM_HostedStoragePool",
                                ResultClass="CIM_StoragePool")

    _operationalStatusValues = None
    pools = []
    for p in spools:
        if p.get("InstanceID") is None:
            continue
        if p.get("Primordial") is True:
            continue
        if p.get("Usage") == 4:
            continue

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, p.classname)
        if p.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(p['OperationalStatus'], _operationalStatusValues)
            p.__setitem__("OperationalStatus", status)

        pools.append(p)

    logger.info("pools: {0}", len(pools))
    return pools


def __getDisksFromDriveViews(_conn, ps_array, controllers):
    disks = []
    diskViews = _conn.Associators(ps_array.path,
                                AssocClass="SNIA_SystemDeviceView",
                                ResultClass="SNIA_DiskDriveView")
    if diskViews is None or len(diskViews) <=0:
        diskViews = []
        for ct in controllers:
            compViews = _conn.Associators(ct.path,
                                AssocClass="SNIA_SystemDeviceView",
                                ResultClass="SNIA_DiskDriveView")
            if compViews is not None and len(compViews) > 0:
                diskViews += compViews

    for view in diskViews:
        # print("view", view.tomof())
        # pull the keys specific to the storage volume from the view of the volume
        creationClassName = view.get("DDCreationClassName")
        v = CIMInstance(classname=creationClassName)
        v.path = CIMInstanceName(classname=creationClassName, namespace=ps_array.path.namespace)
        unsupportedPropertyNames = ()

        for k in view.keys():
            if k.startswith('DD') and k not in unsupportedPropertyNames and view.get(k) is not None:
                v.__setitem__(k[2:], view.get(k))

        for k in view.path.keys():
            if k.startswith('DD') and view.get(k) is not None:
                v.path.__setitem__(k[2:], view.get(k))

        disks.append(v)
    return disks


def __getDiskDrives(_conn, ps_array, controllers):
    disks = []
    disks = _conn.Associators(ps_array.path,
                     AssocClass="CIM_SystemDevice",
                     ResultClass="CIM_DiskDrive")

    if len(disks) == 0:
        for ct in controllers:
            diskComps = _conn.Associators(ct.path,
                        AssocClass="CIM_SystemDevice",
                        ResultClass="CIM_DiskDrive")
            disks += diskComps
    return disks


def getDisks(conn, ps_array, controllers, supportedViews):
    _conn = smisconn(conn)
    if supportedViews.__contains__(u"DiskDriveView"):
        disks = __getDisksFromDriveViews(_conn, ps_array, controllers)
    else:
        disks = __getDiskDrives(_conn, ps_array, controllers)

    if len(disks)<=0:
        disks = _conn.EnumerateInstances("CIM_DiskDrive", ps_array.path.namespace)
        disks = [d for d in disks if d.get("SystemName") == ps_array.get("Name")]

    logger.info("disks: {0}", len(disks))
    _operationalStatusValues = None
    for d in disks:
        getPhysicalPackages(_conn, d)
        getDiskExtents(_conn, d)

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, d.classname)
        if d.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(d['OperationalStatus'], _operationalStatusValues)
            d.__setitem__("OperationalStatus", status)

    logger.info("get physicalPackage extents and operationalStatus for each disks: {0}", len(disks))
    return disks


def getDiskExtents(_conn, disk):
    diskExtents = []
    diskExtents = _conn.Associators(disk.path, AssocClass="CIM_MediaPresent", ResultClass="CIM_StorageExtent")

    if len(diskExtents) <=0:
        return
    extent = diskExtents[0]
    size = long(extent.get("BlockSize") * extent.get("NumberOfBlocks"))
    # print('size', size)
    disk.__setitem__("Capacity", Uint64(size))
    return None


def getPhysicalPackages(_conn, disk):
    packages = []
    for i in (1,3):
        try:
            packages = _conn.Associators(disk.path,  AssocClass="CIM_Realizes", ResultClass="CIM_PhysicalPackage")
            break
        except Exception, e:
            logger.warn("Failed to get physical packages for the disk {0}", disk["DeviceID"])

    packages = [p for p in packages if p.has_key("Manufacturer")]
    if len(packages) <= 0:
        return
    package = packages[0]
    if package.get("Manufacturer") is not None:
        disk.__setitem__("Vendor", package.get("Manufacturer"))

    if package.get("Model") is not None:
        disk.__setitem__("Model", package.get("Model"))

    if package.get("SerialNumber") is not None:
        disk.__setitem__("SerialNumber", package.get("SerialNumber"))
    return None


def __getDiskExtentsMap(_conn, disks):
    diskExtents = {}
    for d in disks:
        extents = _conn.AssociatorNames(d.path,
                                AssocClass="CIM_MediaPresent",
                                ResultClass="CIM_StorageExtent")
        diskExtents[d.path] = extents
    return diskExtents


def __getVolumesFromVolumeViews(_conn, ps_array):
    pool_volume_map = {}
    volume_views = _conn.Associators(ps_array.path,
                            AssocClass="SNIA_SystemDeviceView",
                            ResultClass="SNIA_VolumeView")

    for view in volume_views:
        # pull the keys specific to the storage volume from the view of the volume
        v = CIMInstance(classname=view.get("SVCreationClassName"))
        v.path = CIMInstanceName(classname=view.get("SVCreationClassName"), namespace=ps_array.path.namespace)
        unsupported_property_names = ('SVPrimordial', 'SVNoSinglePointOfFailure',
                                    'SVIsBasedOnUnderlyingRedundancy', 'SVClientSettableUsage')
        for k in view.keys():
            if k.startswith('SV') and k not in unsupported_property_names and view.get(k) is not None:
                v.__setitem__(k[2:], view.get(k))

        for k in view.path.keys():
            if k.startswith('SV') and view.get(k) is not None:
                v.path.__setitem__(k[2:], view.get(k))

        poolID = view.get("SPInstanceID")
        volumes = pool_volume_map.get(poolID);
        if volumes is None:
            volumes = []
            pool_volume_map[poolID] = volumes
        volumes.append(v)
    return pool_volume_map


def __getVolumesFromPools(_conn, pools):
    pool_volume_map = {}
    for p in pools:
        vols = []
        vols = _conn.Associators(p.path,
                        AssocClass="CIM_AllocatedFromStoragePool",
                        ResultClass="CIM_StorageVolume")

        poolID = p.get("InstanceID")
        volumes = pool_volume_map.get(poolID);
        if volumes is None:
            volumes = []
            pool_volume_map[poolID] = volumes
        volumes += vols
    return pool_volume_map


def getPoolVolumesMap(conn, ps_array, pools, supportedViews, extents):
    _conn = smisconn(conn)
    poolVolumeMap = {}
    # Do not allow VolumeViews for Hitachi - they do not provide the necessary attributes in the VolumeView class:
    # specifically "ThinlyProvisioned" and "IsComposite"
    if supportedViews.__contains__(u"VolumeView") and not ps_array.classname.startswith("HITACHI"):
        poolVolumeMap = __getVolumesFromVolumeViews(_conn, ps_array)
    if len(poolVolumeMap) <= 0:
        poolVolumeMap = __getVolumesFromPools(_conn, pools)

    _operationalStatusValues = None
    for poolID in poolVolumeMap.keys():
        volumes = poolVolumeMap.get(poolID)

        for volume in volumes:
            volume.__setitem__('PoolID', poolID)

            if _operationalStatusValues is None:
                _operationalStatusValues = getOperationalStatusValues(conn, ps_array, volume.classname)
            if volume.has_key("OperationalStatus"):
                status = convertOperationalStatusValues(volume['OperationalStatus'], _operationalStatusValues)
                volume.__setitem__("OperationalStatus", status)

            deviceId = volume["DeviceID"]
            if extents.has_key(deviceId):
                extent = extents.get(deviceId)
                if extent.has_key("EMCRaidLevel"):
                    volume.__setitem__("RaidLevel", extent.get("EMCRaidLevel"))
                if extent.has_key("ThinlyProvisioned"):
                    volume.__setitem__("ThinlyProvisioned", str(extent["ThinlyProvisioned"]))

    return poolVolumeMap

def getPoolDiskMap(conn, pools, disks):
    _conn = smisconn(conn)
    disk_extents_map = __getDiskExtentsMap(_conn, disks)

    pool_disk_map = {}
    all_class_names = getClassNames(conn, conn.default_namespace, None)
    has_disk_drive_class = {"CIM_ConcreteDependency", "CIM_DiskDrive"}.issubset(all_class_names)
    for p in pools:
        is_primordial = p.get("Primordial")
        if is_primordial is None:
            continue

        pool_disks = []
        if has_disk_drive_class:
            pool_disks = _conn.AssociatorNames(p.path,
                            AssocClass="CIM_ConcreteDependency",
                            ResultClass="CIM_DiskDrive",
                            Role="Dependent",
                            ResultRole="Antecedent")
            pool_disk_map[p.get("InstanceID")] = pool_disks

        if len(pool_disks) <= 0:
            poolDiskExtentPaths = _conn.AssociatorNames(p.path,
                            AssocClass="CIM_ConcreteComponent",
                            ResultClass="CIM_StorageExtent",
                            Role="GroupComponent",
                            ResultRole="PartComponent")
            # print("poolDiskExtentPaths: ", len(poolDiskExtentPaths))
            diskPaths = []
            for extentPath in poolDiskExtentPaths:
                for diskPath in disk_extents_map.keys():
                    if disk_extents_map.get(diskPath).__contains__(extentPath):
                        if not diskPaths.__contains__(diskPath):
                            diskPaths.append(diskPath)

            pool_disk_map[p.get("InstanceID")] = diskPaths
    return pool_disk_map


def getMaskingMappingViews(conn, array):
    _conn = smisconn(conn)
    logger.info("Start to get MaskingMappingViews")
    mVolumeMappingMaskingLookup = {}
    try:
        hardwareIDMgmtServices = _conn.AssociatorNames(array.path,
                                     AssocClass="CIM_HostedService",
                                     ResultClass="CIM_StorageHardwareIDManagementService")
        if hardwareIDMgmtServices is None or 0 >= len(hardwareIDMgmtServices):
            logger.info("No hardware ID management service for storage array {0}", array.getItem("ElementName"))
            return False


        storageHarwareIDs = _conn.Associators(hardwareIDMgmtServices[0],
                                     AssocClass="CIM_ConcreteDependency",
                                     ResultClass="CIM_StorageHardwareID")
        if storageHarwareIDs is None or 0 >= len(storageHarwareIDs):
            logger.info("No hardware IDs found for storage array {0}", array.getItem("ElementName"))
            return False

        for hardwareID in storageHarwareIDs:
            views = _conn.References(hardwareID.path,
                                    ResultClass="SNIA_MaskingMappingView")

            for view in views:
                # print("view",  view.tomof())
                volumeID = view.get("LogicalDevice")
                volumeMappingViews = mVolumeMappingMaskingLookup[volumeID]
                if volumeMappingViews is None:
                    volumeMappingViews = []
                    mVolumeMappingMaskingLookup[volumeID] = volumeMappingViews
                volumeMappingViews.append(view)

    except Exception, e:
        logger.error("Failed to get MaskingMappingViews: {0}", e.message)
    logger.info("get MaskingMappingViews {0}", len(mVolumeMappingMaskingLookup))
    return mVolumeMappingMaskingLookup


def getSCSIProtocolControllers(conn, array):
    _conn = smisconn(conn)
    logger.info("Start to get SCSIProtocolControllers")
    kSCSIProtocolControllerPropList = [
        "SystemCreationClassName",
        "SystemName",
        "CreationClassName",
        "DeviceID",
        "Name",
        "NameFormat",
        "ElementName"
    ]
    kProtocolControllerForUnitPropList = [
        "CreationClassName",
        "DeviceID",
        "SystemCreationClassName",
        "SystemName",
        "DeviceNumber"
    ]
    kNetworkPortPropList = [
        "SystemCreationClassName",
        "SystemName",
        "CreationClassName",
        "DeviceID",
        "PermanentAddress"
    ]

    mSCSIProtocolControllers = {}
    mStorageHardwareIDLookup = None
    mAuthorizedSubjectLookup = None
    try:
        # CIM_ProtocolControllerMaskingCapabilities: Defines characteristics of how volumes
        # can be mapped/masked on the storage array controller ports.
        PCMCs = _conn.Associators(array.path,
                                    AssocClass="CIM_ElementCapabilities",
                                    ResultClass="CIM_ProtocolControllerMaskingCapabilities")
        SPCs = None

        configSvc = _conn.AssociatorNames(array.path,
                                    AssocClass="CIM_HostedService",
                                    ResultClass="CIM_ControllerConfigurationService")

        if configSvc is not None and 0 < len(configSvc):
            # Get only SCSIProtocolControllers for this system
            try:
                SPCs = _conn.Associators(configSvc[0],
                                    AssocClass="CIM_ConcreteDependency",
                                    ResultClass="CIM_SCSIProtocolController",
                                    PropertyList=kSCSIProtocolControllerPropList)
            except Exception as e:
                logger.warn("Failed to get SCSIProtocolControllers for this system %s" % e.message)

        if SPCs is None:
            # some use this association (conformant?)
            try:
                SPCs = _conn.Associators(array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_SCSIProtocolController",
                                    PropertyList=kSCSIProtocolControllerPropList)
            except Exception as e:
                logger.warn("Failed to get SCSIProtocolController %s " % e.message)

        if SPCs is None:
            # Desperate measures...Get all SCSIProtocolControllers found on the CIMOM
            try:
                SPCs = _conn.EnumerateInstances("CIM_SCSIProtocolController", PropertyList=kSCSIProtocolControllerPropList)
            except Exception as e:
                logger.warn("Failed to enumerate intances of CIM_SCSIProtocolController. %s" % e.message)

        if SPCs is None or 0 >= len(SPCs):
            logger.info("No SCSIProtocolControllers found for Storage Array \"{0}\"", array["ElementName"])
            return

        # Cache the storage hardware ID and authorized subject instances
        if mStorageHardwareIDLookup is None:
            mStorageHardwareIDLookup = {}
            objs = _conn.EnumerateInstances("CIM_StorageHardwareID",
                                    namespace = array.path.namespace,
                                    DeepInheritance = True)
            for obj in objs:
                obj.path.host = array.path.host
                mStorageHardwareIDLookup[obj.path.__str__()] = obj


        if mAuthorizedSubjectLookup is None:
            mAuthorizedSubjectLookup = {}
            assocs = _conn.EnumerateInstances("CIM_AuthorizedSubject",
                                           namespace=array.path.namespace,
                                           DeepInheritance=True)

            for ci in assocs:
                mAuthorizedSubjectLookup[ci] = ci

        # print(mAuthorizedSubjectLookup)
        for spc in SPCs:
            # Add StorageHardwareIDs associated with the SCSIProtocolController
            authPrivileges = _conn.AssociatorNames(spc.path,
                                    AssocClass="CIM_AuthorizedTarget",
                                    ResultClass="CIM_AuthorizedPrivilege")
            if authPrivileges is not None and 0 < len(authPrivileges):
                for ap in authPrivileges:
                    storHardwareIDs = getAssociatedEntities(ap, mAuthorizedSubjectLookup, mStorageHardwareIDLookup)
                    # initiators
                    if storHardwareIDs is not None and len(storHardwareIDs) > 0:
                        hardwareIDs = spc.get("storHardwareIDs", [])
                        hardwareIDs += storHardwareIDs
                        spc.__setitem__("storHardwareIDs", hardwareIDs)

            # The CIM_ProtocolControllerForUnit associates a Volume to this SPC. It contains a property,
            # "DeviceNumber", that is the LUN of this association of a Volume to a Port.
            pcfuLookup = {}
            pcfus = _conn.References(spc.path,
                                        ResultClass="CIM_ProtocolControllerForUnit",
                                        Role="Antecedent",
                                        includeClassOrigin=False,
                                        PropertyList=kProtocolControllerForUnitPropList)

            for pcfu in pcfus:
                pcPath = pcfu.path.get("Antecedent")
                volumePath = pcfu.path.get("Dependent")
                key = pcPath.__str__() + volumePath.__str__()

                if not pcfuLookup.__contains__(key):
                    pcfuLookup[key] = pcfu
                    pcfus = spc.get("pcfus", [])
                    pcfus.append(pcfu)
                    spc.__setitem__("pcfus", pcfus)

                    spcList = mSCSIProtocolControllers.get(volumePath.__str__())
                    if spcList is None:
                        spcList = []
                        mSCSIProtocolControllers[volumePath.__str__()] = spcList

                    spcList.append(spc)


            nameFormat = spc.get("NameFormat")
            spcName = spc.get("Name")
            isISCSI = "iSCSI Name" == nameFormat or (spcName is not None and spcName.__contains__("iqn"))
            # print("isISCSI", isISCSI, nameFormat, spcName)
            # print(spc.tomof())

            # Add FCPorts associated with the SCSIProtocolController
            # FCPort is associated to a SCSIProtocolController through
            # SAPAvailableForElement -> SCSIProtocolEndpoint -> DeviceSAPImplementation
            SPEs = _conn.Associators(spc.path,
                                        AssocClass="CIM_SAPAvailableForElement",
                                        ResultClass="CIM_SCSIProtocolEndpoint")
            for spe in SPEs:
                speName= spe.get("Name")
                # print("speName: ", speName, spe.path)
                if spe.get("CreationClassName").startswith("HPEVA_"):
                    spe.path.__delitem__("SystemName")   #remove unused condition

                if isISCSI or (speName is not None and speName.__contains__("iqn")):
                    spe.__setitem__("PermanentAddress", speName)
                    spc.__setitem__("spe", spe)
                else:
                    try:
                        ports = _conn.Associators(spe.path,
                                            AssocClass="CIM_DeviceSAPImplementation",
                                            ResultClass="CIM_NetworkPort",
                                            PropertyList=kNetworkPortPropList)
                        if ports is not None and len(ports) > 0:
                            spc_ports = spc.get("ports", [])
                            spc_ports += ports
                            spc.__setitem__("ports", spc_ports)
                    except Exception, e:
                        logger.warn('Failed to associate {0} to ports', spe.path)
                # print(speName, spe.tomof())

    except Exception, e:
        logger.error('Failed to get SCSIProtocolControllers: {0}', traceback.format_exc())
    return mSCSIProtocolControllers


def getAssociatedEntities(entity, assocs, entities):
    result = []
    for assoc in assocs.values():
        refs = assoc.values()
        found = False
        objResult = None

        if refs[0] == entity:
            objResult = entities.get(refs[1].__str__())
            if objResult is not None:
                found = True

        if not found:
            if refs[1] == entity:
                objResult = entities.get(refs[0].__str__())
                if objResult is not None:
                    found = True

        if found:
            result.append(objResult)

    return result

def getAllControllerStatistics(conn, controllers, statAssociations, statObjectMap):
    controllerStats = []
    for c in controllers:
        controllerStat = getControllerStatistics(conn, c, statAssociations, statObjectMap)
        if len(controllerStat) > 0:
            controllerStats += controllerStat
    logger.debug("controllerStatistics: {0}", len(controllerStats))
    return controllerStats

def getControllerStatistics(conn, controller, statAssociations, statObjectMap):
    controller_stat = getAssociatedStatistics(conn, controller.path, statAssociations, statObjectMap)
    # print("controller_stat", controller_stat)

    if controller_stat is None or len(controller_stat) <= 0:
        try:
            controller_stat = getStorageStatisticsData(conn, controller.path)
        except:
            pass

    if len(controller_stat) > 0:
        controller_stat[0].__setitem__("statID", controller["ElementName"].upper())
        controller_stat[0].__setitem__("OperationalStatus", controller["OperationalStatus"])
    return controller_stat


def getAllPortStatistics(conn, ports, statAssociations, statObjectMap):
    fcPortStats = []
    for p in ports:
        portStat = getPortStatistics(conn, p, statAssociations, statObjectMap)
        if len(portStat) > 0:
            fcPortStats += portStat
    return fcPortStats

def getPortStatistics(conn, port, statAssociations, statObjectMap):
    port_stat = getAssociatedStatistics(conn, port.path, statAssociations, statObjectMap)

    if port_stat is None or len(port_stat) <= 0:
        # print("port.path: ", port.path)
        port_stat = getStorageStatisticsData(conn, port.path)

    if len(port_stat) > 0:
        port_stat[0].__setitem__("statID", _get_state_id(port))
        port_stat[0].__setitem__("OperationalStatus", port["OperationalStatus"])
        if port.has_key("Speed"):
            port_stat[0].__setitem__("Speed", port["Speed"])
        if port.has_key("MaxSpeed"):
            port_stat[0].__setitem__("MaxSpeed", port["MaxSpeed"])

    return port_stat

def _get_state_id(port):
    stat_id = None
    try:
        if port.has_key("PermanentAddress"):
            stat_id = port["PermanentAddress"]
        else:
            wwn = port["Name"]
            if wwn is not None:
                comma = wwn.find(',')
                if 0 < comma:
                    wwn = wwn[0:comma]
                stat_id = wwn
        logger.debug("port {0}", stat_id)
    except Exception,e:
        logger.error(traceback.format_exc(e))
    return stat_id

def getAllDiskStatistics(conn, disks, statAssociations, statObjectMap, class_names, diskStatDicts):
    diskStats = []
    isMediaPresent = {"CIM_MediaPresent", "CIM_StorageExtent"}.issubset(class_names)
    for d in disks:
        diskStatDict = diskStatDicts[d["Name"]] if diskStatDicts.has_key(d["Name"]) else None
        diskStat = getDiskStatistics(conn, d, statAssociations, statObjectMap, isMediaPresent, diskStatDict)
        if len(diskStat) > 0:
            diskStats += diskStat
    logger.info("diskStats: {0}", len(diskStats))
    return diskStats

def getDiskStatistics(conn, disk, statAssociations, statObjectMap, isMediaPresent, diskStatDict):
    _conn = smisconn(conn)
    disk_stat = []
    on_media = False     #TODO if stats for disks are associated with the media on this SMI provider

    if not on_media:
        disk_stat = getAssociatedStatistics(conn, disk.path, statAssociations, statObjectMap)
        if disk_stat is None or len(disk_stat) <= 0:
            disk_stat = getStorageStatisticsData(conn, disk.path)

    if disk_stat is None or len(disk_stat) <= 0:
        medias = []
        if isMediaPresent:
            medias = _conn.AssociatorNames(disk.path,
                              AssocClass="CIM_MediaPresent",
                              ResultClass="CIM_StorageExtent")

        if len(medias) > 0:
            disk_stat = getAssociatedStatistics(conn, medias[0], statAssociations, statObjectMap)
            if disk_stat is None or len(disk_stat) <= 0:
                disk_stat = getStorageStatisticsData(conn, medias[0])

    if len(disk_stat) <= 0 and diskStatDict is not None:
        disk_stat[0] = diskStatDict

    if len(disk_stat) > 0:
        logger.info("get disk statistics {0} ", disk["DeviceID"])
        disk_stat[0].__setitem__("statID", disk["DeviceID"].upper())
        disk_stat[0].__setitem__("OperationalStatus", disk["OperationalStatus"])

    return disk_stat


def getAllVolumeStatistics(conn, volumes, statAssociations, statObjectMap, volumeStatDicts):
    volumeStats = []
    for v in volumes:
        volumeStatDict = volumeStatDicts[v["Name"]] if volumeStatDicts.has_key(v["Name"]) else None
        volumeStat = getVolumeStatistics(conn, v, statAssociations, statObjectMap, volumeStatDict)
        if len(volumeStat) > 0:
            volumeStats += volumeStat
    logger.info("volumeStats: {0}", len(volumeStats))
    return volumeStats


def getVolumeStatistics(conn, volume, statAssociations, statObjectMap, volumeStatDict):
    volume_stat = getAssociatedStatistics(conn, volume.path, statAssociations, statObjectMap)

    if volume_stat is None or len(volume_stat) <= 0:
        volume_stat = getStorageStatisticsData(conn, volume.path)

    if len(volume_stat) <= 0 and volumeStatDict is not None:
        volume_stat[0] = volumeStatDict

    if len(volume_stat) > 0:
        volume_stat[0].__setitem__("uuid", volume["Name"])
        volume_stat[0].__setitem__("statID", volume["DeviceID"])
        if volume.has_key("OperationalStatus"):
            volume_stat[0].__setitem__("OperationalStatus", volume["OperationalStatus"])
        if volume.has_key("HealthState") and volume["HealthState"] is not None:
            volume_stat[0].__setitem__("HealthState", volume["HealthState"])
        if volume.has_key("BlockSize"):
            volume_stat[0].__setitem__("BlockSize", volume["BlockSize"])
        if volume.has_key("ConsumableBlocks"):
            volume_stat[0].__setitem__("ConsumableBlocks", volume["ConsumableBlocks"])
        if volume.has_key("NumberOfBlocks"):
            volume_stat[0].__setitem__("NumberOfBlocks", volume["NumberOfBlocks"])
    return volume_stat


def getStorageStatisticsData(conn, path):
    _conn = smisconn(conn)
    stat = []
    stat = _conn.Associators(path, AssocClass="CIM_ElementStatisticalData",
                              ResultClass="CIM_BlockStorageStatisticalData")
    # CIM_BlockStorageStatisticalData
    return stat


def getAssociatedStatistics(conn, path, statAssociations, statDataMap):
    for assoc in statAssociations:
        managed_element = assoc.get("ManagedElement")
        stats = assoc.get("Stats")
        if managed_element == path:
            stats_val = None
            if stats.has_key("InstanceID"):
                stats_val = statDataMap.get(stats["InstanceID"])
            if stats_val is None:
                for v in statDataMap.values():
                    if v.has_key("ElementName") and managed_element.has_key("DeviceID")\
                            and v["ElementName"] == managed_element["DeviceID"]:
                        stats_val = v
                        break

            if stats_val is not None: return [stats_val]

            # return [statDataMap.get(stats["InstanceID"])]
    return []


def getStatObjectMap(conn, NAMESPACE):
    _conn = smisconn(conn)
    stat_object_map = {}
    # CIM_BlockStorageStatisticalData
    statObjects = _conn.EnumerateInstances("CIM_StatisticalData",
                                        namespace=NAMESPACE, DeepInheritance=True)

    logger.info("statObjects total: {0}", len(statObjects))
    # if statObjects is not None and len(statObjects) > 0:
    #     for statObj in statObjects:
    #         logger.debug("statObject : {0}", statObj.tomof())

    for d in statObjects:
        if d.has_key("InstanceID"):
            stat_object_map[d["InstanceID"]] = d
        elif d.path.has_key("InstanceID"):
            stat_object_map[d.path["InstanceID"]] = d
        # print(d.path["InstanceID"])

    logger.info("len(statDatas): {0}", len(stat_object_map))
    return stat_object_map


def getStatAssociations(conn, NAMESPACE):
    _conn = smisconn(conn)
    stat_associations = {}

    stat_associations = _conn.EnumerateInstances("CIM_ElementStatisticalData",
                                namespace=NAMESPACE, DeepInheritance=True)

    logger.info("len(statAssociations): {0}", len(stat_associations))
    return stat_associations

def getClassNames(conn, NAMESPACE, filter):
    _conn = smisconn(conn)
    classNames = _conn.EnumerateClassNames(namespace=NAMESPACE, DeepInheritance=True)
    if filter:
        classNames = [c for c in classNames if filter(c)]
    return sorted(classNames)


def getBlockStorageViewsSupported(conn):
    _conn = smisconn(conn)
    profiles = _conn.EnumerateInstances("CIM_RegisteredProfile")
    profiles = [s for s in profiles if s.get("RegisteredName") == 'Block Storage Views']

    subprofiles = _conn.EnumerateInstances("CIM_RegisteredSubprofile")
    subprofiles = [s for s in subprofiles if s.get("RegisteredName") == 'Block Storage Views']

    isBlockStorageViewsSupported = len(profiles) > 0 or len(subprofiles) > 0
    logger.info("isBlockStorageViewsSupported: {0}", isBlockStorageViewsSupported)
    return isBlockStorageViewsSupported


def hasStatisticalDataClass(conn, __namespace, all_class_names):
    return {"CIM_ElementStatisticalData", "CIM_BlockStorageStatisticalData"}.issubset(all_class_names)

def getStatsCapabilities(conn, array):
    _conn = smisconn(conn)
    statsService = _conn.AssociatorNames(array.path,
                                        AssocClass="CIM_HostedService",
                                        ResultClass="CIM_BlockStatisticsService")

    if statsService is None or len(statsService) < 1:
        statsService = _conn.AssociatorNames(array.path,
                                        AssocClass="CIM_HostedService",
                                        ResultClass="CIM_StorageConfigurationService")

    if statsService is None or len(statsService) < 1:
        logger.info('No Storage Statistics Service found')
        return None


    statsCaps = _conn.Associators(statsService[0],
                                        AssocClass="CIM_ElementCapabilities",
                                        ResultClass="CIM_BlockStatisticsCapabilities")

    if statsCaps is None or len(statsCaps) < 1:
        logger.info('No Storage Statistics Capabilities found')
        return None

    logger.info('statsCaps', statsCaps[0].tomof())
    return statsCaps[0]

def detectInteropNamespace(conn):
    namespaces = ("interop", "root", "root/interop", "pg_interop", "root/pg_interop", "root/cimv2", "root/compellent",
                  "root/eternus", "root/hitachi/smis", "root/smis/current",
                  "root/hitachi/dm55", "root/hitachi/dm42", "root/hpmsa", "root/ema",
                  "root/tpd", "root/emc", "root/eva", "root/ibm", "root/hpq", "purestorage")
    is_first = True
    for np in namespaces:
        conn.default_namespace = np
        try:
            # RegisteredProfile
            profiles = conn.EnumerateInstanceNames("CIM_Namespace")
            if profiles is not None and len(profiles) > 0:
                break
        except Exception, e:
            logger.warn("trying namespace {0} found exception {1}", np, e.message)
            if is_first:
                is_first = False
                # traceback.print_stack()

    logger.info("found the interop namespace, current namespace is {0}", conn.default_namespace)
