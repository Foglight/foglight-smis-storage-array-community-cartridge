# coding=utf-8
from __future__ import print_function

import string
import traceback
import foglight.logging
from smisconn import smisconn

from pywbemReq.cim_obj import CIMInstanceName, CIMInstance
from pywbemReq.cim_operations import is_subclass
from pywbemReq.cim_types import *

logger = foglight.logging.get_logger("smis-agent")

def getRegisteredProfiles(conn):
    kProfilePropList = ["InstanceID", "RegisteredVersion", "RegisteredName"]
    profiles = conn.EnumerateInstances("CIM_RegisteredProfile", DeepInheritance=True, PropertyList=kProfilePropList)
    return profiles

def getElementsForProfile(conn, profileName):
    profiles = getRegisteredProfiles(conn)
    profiles = [p for p in profiles if p.get("RegisteredName") == profileName]
    profiles = profiles[:1]
    logger.info('profiles: %d' % len(profiles))

    elements = []
    for p in profiles:
        managedElements = conn.Associators(p.path,
                                AssocClass="CIM_ElementConformsToProfile",
                                Role="ConformantStandard",
                                ResultRole="ManagedElement")
        for managedElement in managedElements:
            if managedElement.get("ElementName") is None or managedElement.get("ElementName") == "":
                managedElement.__setitem__("ElementName", managedElement.get("Name"))
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
            continue

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, m, m.classname)
        status = convertOperationalStatusValues(m['OperationalStatus'], _operationalStatusValues)
        m.__setitem__("OperationalStatus", status)

        arrays.append(m)
    return arrays


def getProductInfo(conn, ps_array):
    physpacks = conn.Associators(ps_array.path,
                                AssocClass="CIM_SystemPackaging",
                                ResultClass="CIM_PhysicalPackage")
    if physpacks is None:
        return False

    use_chassis = None
    if len(physpacks) == 1:
        use_chassis = physpacks[0]
    else:
        for p in physpacks:
            if p.get("ChassisPackageType") in ("17", "22"):
                use_chassis = p
                break
        if use_chassis is None and len(physpacks)>0:
            use_chassis = physpacks[0]

    if use_chassis is None:
        return False

    products = conn.Associators(use_chassis.path,
                                AssocClass="CIM_ProductPhysicalComponent",
                                ResultClass="CIM_Product")
    if products is None:
        return False


    model = use_chassis.get("Model")
    if model is not None:
        model = string.replace(model, "Rack Mounted ", "")
        model = string.replace(model, '_', '-')
        ps_array.__setitem__("Model", model)

    product = products[0]
    vendor = product.get("Vendor")
    if vendor is not None:
        ps_array.__setitem__("Vendor", vendor)

    ps_array.__setitem__("Product", product.get("Name"))
    ps_array.__setitem__("SerialID", product.get("IdentifyingNumber"))
    ps_array.__setitem__("Version", product.get("Version"))

    return True

def getViewCapabilities(conn, ps_array):
    viewCaps = conn.Associators(ps_array.path,
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
    cls = conn.GetClass(className,
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
    comps = conn.Associators(ps_array.path,
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

        if c.classname.startswith("HPEVA"):
            c.path.__delitem__("Name")
            c.path.__setitem__("ElementName", c.get("ElementName"))


        software_identities = conn.Associators(c.path, AssocClass="CIM_InstalledSoftwareIdentity",
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
    fc_ports = []
    if len(controllers) <= 0:
        return fc_ports

    for ct in controllers:
        try:
            ports = conn.Associators(ct.path, AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort",
                                    Role="GroupComponent",
                                    ResultRole="PartComponent")

            if ports is None or  len(ports) <= 0:
                logger.warn("No FC ports found for %s using %s" % (ct.get("ElementName"),  conn) )
                controllers.remove(ct)
            else:
                for p in ports:
                    p.__setitem__("ControllerName", ct.get("ElementName"))
                fc_ports += ports
        except Exception as err:
            logger.error("getFcPorts Error: %s" % err.message)

    if len(fc_ports) <= 0 and len(controllers) > 0:
        fc_ports = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort")
        for p in fc_ports:
            p.__setitem__("ControllerName", controllers[0].get("ElementName"))

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


def getIscisiPorts(conn, ps_array, controllers):
    iscsi_ports = []
    if len(controllers) <= 0:
        return iscsi_ports

    try:
        for ct in controllers:
            ports = conn.Associators(ct.path,
                                    AssocClass="CIM_HostedAccessPoint",
                                    ResultClass="CIM_iSCSIProtocolEndpoint")
            if ports:
                for p in ports:
                    p.__setitem__("ControllerName", ct.get("ElementName"))
                iscsi_ports += ports
    except Exception as err:
        logger.error("getIscisiPorts Error: %s" % err.message)

    if len(iscsi_ports) <= 0:
        iscsi_ports = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort")

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
    extents = conn.Associators(ps_array.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_StorageExtent")
    if len(extents) == 0:
        for ct in controllers:
            extentComps = conn.Associators(ct.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_StorageExtent")
            extents += extentComps

    extentLookup = {}
    for extent in extents:
        if extent.has_key("DeviceID"):
            extentLookup[extent.path] = extent
    return extentLookup


def getPools(conn, ps_array):
    spools = conn.Associators(ps_array.path,
                                AssocClass="CIM_HostedStoragePool",
                                ResultClass="CIM_StoragePool")

    _operationalStatusValues = None
    pools = []
    for p in spools:
        if p.get("InstanceID") is None:
            continue
        if p.get("Primordial") is True:
            continue

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, p.classname)
        if p.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(p['OperationalStatus'], _operationalStatusValues)
            p.__setitem__("OperationalStatus", status)

        pools.append(p)

    logger.info("pools: {0}", len(pools))
    return pools


def __getDisksFromDriveViews(conn, ps_array, controllers):
    disks = []
    diskViews = conn.Associators(ps_array.path,
                                AssocClass="SNIA_SystemDeviceView",
                                ResultClass="SNIA_DiskDriveView")
    if diskViews is None or len(diskViews) <=0:
        diskViews = []
        for ct in controllers:
            compViews = conn.Associators(ct.path,
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


def __getDiskDrives(conn, ps_array, controllers):
    disks = []
    try:
        disks = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_DiskDrive")
        if len(disks) == 0:
            for ct in controllers:
                diskComps = conn.Associators(ct.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_DiskDrive")
                disks += diskComps
    except:
        logger.error(traceback.format_exc())
    return disks


def getDisks(conn, ps_array, controllers, supportedViews):
    if supportedViews.__contains__(u"DiskDriveView"):
        disks = __getDisksFromDriveViews(conn, ps_array, controllers)
    else:
        disks = __getDiskDrives(conn, ps_array, controllers)

    if len(disks)<=0:
        disks = conn.EnumerateInstances("CIM_DiskDrive", ps_array.path.namespace)
        disks = [d for d in disks if d.get("SystemName") == ps_array.get("Name")]

    _operationalStatusValues = None
    for d in disks:
        getPhysicalPackages(conn, d)
        getDiskExtents(conn, d)

        if _operationalStatusValues is None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, d.classname)
        if d.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(d['OperationalStatus'], _operationalStatusValues)
            d.__setitem__("OperationalStatus", status)

    logger.info("disks: {0}", len(disks))
    return disks


def getDiskExtents(conn, disk):
    diskExtents = conn.Associators(disk.path, AssocClass="CIM_MediaPresent", ResultClass="CIM_StorageExtent")
    if len(diskExtents) <=0:
        return
    extent = diskExtents[0]
    size = long(extent.get("BlockSize") * extent.get("NumberOfBlocks"))
    # print('size', size)
    disk.__setitem__("Capacity", Uint64(size))
    return None


def getPhysicalPackages(conn, disk):
    packages = conn.Associators(disk.path,  AssocClass="CIM_Realizes", ResultClass="CIM_PhysicalPackage")
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


def getDiskExtentsMap(conn, disks):
    diskExtents = {}
    for d in disks:
        extents = conn.AssociatorNames(d.path,
                                AssocClass="CIM_MediaPresent",
                                ResultClass="CIM_StorageExtent")
        diskExtents[d.path] = extents
    return diskExtents


def __getVolumesFromVolumeViews(conn, ps_array):
    pool_volume_map = {}
    try:
        volume_views = conn.Associators(ps_array.path,
                                AssocClass="SNIA_SystemDeviceView",
                                ResultClass="SNIA_VolumeView")
    except Exception as e:
        logger.error(e)

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


def __getVolumesFromPools(conn, pools):
    pool_volume_map = {}
    for p in pools:
        vols = []
        try:
            vols = conn.Associators(p.path,
                            AssocClass="CIM_AllocatedFromStoragePool",
                            ResultClass="CIM_StorageVolume")
        except Exception as e:
            logger.error(traceback.format_exc())

        poolID = p.get("InstanceID")
        volumes = pool_volume_map.get(poolID);
        if volumes is None:
            volumes = []
            pool_volume_map[poolID] = volumes
        volumes += vols
    return pool_volume_map


def getPoolVolumesMap(conn, ps_array, pools, supportedViews):
    poolVolumeMap = {}
    # Do not allow VolumeViews for Hitachi - they do not provide the necessary attributes in the VolumeView class:
    # specifically "ThinlyProvisioned" and "IsComposite"
    if supportedViews.__contains__(u"VolumeView") and not ps_array.classname.startswith("HITACHI"):
        poolVolumeMap = __getVolumesFromVolumeViews(conn, ps_array)
    if len(poolVolumeMap) <= 0:
        poolVolumeMap = __getVolumesFromPools(conn, pools)

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

    return poolVolumeMap

def getPoolDiskMap(conn, pools, disks):
    diskExtentsMap = getDiskExtentsMap(conn, disks)

    poolDiskMap = {}
    all_class_names = getClassNames(conn, conn.default_namespace, None)
    has_disk_drive_class = {"CIM_ConcreteDependency", "CIM_DiskDrive"}.issubset(all_class_names)
    for p in pools:
        isPrimordial = p.get("Primordial")
        if isPrimordial is None:
            continue

        poolDisks = []
        if has_disk_drive_class:
            poolDisks = conn.AssociatorNames(p.path,
                            AssocClass="CIM_ConcreteDependency",
                            ResultClass="CIM_DiskDrive",
                            Role="Dependent",
                            ResultRole="Antecedent")
            # print("poolDisks: ", len(poolDisks))
            poolDiskMap[p.get("InstanceID")] = poolDisks

        if len(poolDisks) <= 0:

            poolDiskExtentPaths = conn.AssociatorNames(p.path,
                            AssocClass="CIM_ConcreteComponent",
                            ResultClass="CIM_StorageExtent",
                            Role="GroupComponent",
                            ResultRole="PartComponent")
            # print("poolDiskExtentPaths: ", len(poolDiskExtentPaths))
            diskPaths = []
            for extentPath in poolDiskExtentPaths:
                for diskPath in diskExtentsMap.keys():
                    if diskExtentsMap.get(diskPath).__contains__(extentPath):
                        if not diskPaths.__contains__(diskPath):
                            diskPaths.append(diskPath)

            poolDiskMap[p.get("InstanceID")] = diskPaths
    return poolDiskMap


def getMaskingMappingViews(conn, array):
    logger.info("Start to get MaskingMappingViews")
    mVolumeMappingMaskingLookup = {}
    try:
        hardwareIDMgmtServices = conn.AssociatorNames(array.path,
                                     AssocClass="CIM_HostedService",
                                     ResultClass="CIM_StorageHardwareIDManagementService")
        if hardwareIDMgmtServices is None or 0 >= len(hardwareIDMgmtServices):
            logger.info("No hardware ID management service for storage array {0}", array.getItem("ElementName"))
            return False


        storageHarwareIDs = conn.Associators(hardwareIDMgmtServices[0],
                                     AssocClass="CIM_ConcreteDependency",
                                     ResultClass="CIM_StorageHardwareID")
        if storageHarwareIDs is None or 0 >= len(storageHarwareIDs):
            logger.info("No hardware IDs found for storage array {0}", array.getItem("ElementName"))
            return False

        for hardwareID in storageHarwareIDs:
            views = conn.References(hardwareID.path,
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
        PCMCs = conn.Associators(array.path,
                                    AssocClass="CIM_ElementCapabilities",
                                    ResultClass="CIM_ProtocolControllerMaskingCapabilities")
        SPCs = None

        configSvc = conn.AssociatorNames(array.path,
                                    AssocClass="CIM_HostedService",
                                    ResultClass="CIM_ControllerConfigurationService")

        if configSvc is not None and 0 < len(configSvc):
            # Get only SCSIProtocolControllers for this system
            SPCs = conn.Associators(configSvc[0],
                                    AssocClass="CIM_ConcreteDependency",
                                    ResultClass="CIM_SCSIProtocolController",
                                    PropertyList=kSCSIProtocolControllerPropList)
        if SPCs is None:
            # some use this association (conformant?)
            SPCs = conn.Associators(array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_SCSIProtocolController",
                                    PropertyList=kSCSIProtocolControllerPropList)

        if SPCs is None:
            # Desperate measures...Get all SCSIProtocolControllers found on the CIMOM
            SPCs = conn.EnumerateInstances("CIM_SCSIProtocolController", PropertyList=kSCSIProtocolControllerPropList)

        if SPCs is None or 0 >= len(SPCs):
            logger.info("No SCSIProtocolControllers found for Storage Array \"{0}\"", array["ElementName"])
            return

        # Cache the storage hardware ID and authorized subject instances
        if mStorageHardwareIDLookup is None:
            mStorageHardwareIDLookup = {}
            objs = conn.EnumerateInstances("CIM_StorageHardwareID",
                                    namespace = array.path.namespace,
                                    DeepInheritance = True)
            for obj in objs:
                obj.path.host = array.path.host
                mStorageHardwareIDLookup[obj.path.__str__()] = obj


        if mAuthorizedSubjectLookup is None:
            mAuthorizedSubjectLookup = {}
            assocs = conn.EnumerateInstances("CIM_AuthorizedSubject",
                                           namespace=array.path.namespace,
                                           DeepInheritance=True)

            for ci in assocs:
                mAuthorizedSubjectLookup[ci] = ci

        # print(mAuthorizedSubjectLookup)
        for spc in SPCs:
            # Add StorageHardwareIDs associated with the SCSIProtocolController
            authPrivileges = conn.AssociatorNames(spc.path,
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
            pcfus = conn.References(spc.path,
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
            SPEs = conn.Associators(spc.path,
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
                    ports = conn.Associators(spe.path,
                                        AssocClass="CIM_DeviceSAPImplementation",
                                        ResultClass="CIM_NetworkPort",
                                        PropertyList=kNetworkPortPropList)
                    if ports is not None and len(ports) > 0:
                        spc_ports = spc.get("ports", [])
                        spc_ports += ports
                        spc.__setitem__("ports", spc_ports)
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
        port_stat[0].__setitem__("statID", port["PermanentAddress"])
        port_stat[0].__setitem__("OperationalStatus", port["OperationalStatus"])
        port_stat[0].__setitem__("Speed", port["Speed"])
        if port.has_key("MaxSpeed"):
            port_stat[0].__setitem__("MaxSpeed", port["MaxSpeed"])
    return port_stat


def getAllDiskStatistics(conn, disks, statAssociations, statObjectMap, class_names):
    diskStats = []
    isMediaPresent = {"CIM_MediaPresent", "CIM_StorageExtent"}.issubset(class_names)
    for d in disks:
        diskStat = getDiskStatistics(conn, d, statAssociations, statObjectMap, isMediaPresent)
        if len(diskStat) > 0:
            diskStats += diskStat
    logger.info("diskStats: {0}", len(diskStats))
    return diskStats

def getDiskStatistics(conn, disk, statAssociations, statObjectMap, isMediaPresent):
    disk_stat = []
    on_media = False     #TODO if stats for disks are associated with the media on this SMI provider

    if not on_media:
        disk_stat = getAssociatedStatistics(conn, disk.path, statAssociations, statObjectMap)
        if disk_stat is None or len(disk_stat) <= 0:
            disk_stat = getStorageStatisticsData(conn, disk.path)

    if disk_stat is None or len(disk_stat) <= 0:
        medias = []
        if isMediaPresent:
            medias = conn.AssociatorNames(disk.path,
                                      AssocClass="CIM_MediaPresent",
                                      ResultClass="CIM_StorageExtent")
        if len(medias) > 0:
            disk_stat = getAssociatedStatistics(conn, medias[0], statAssociations, statObjectMap)
            if disk_stat is None or len(disk_stat) <= 0:
                disk_stat = getStorageStatisticsData(conn, medias[0])

    if len(disk_stat) > 0:
        disk_stat[0].__setitem__("statID", disk["DeviceID"].upper())
        disk_stat[0].__setitem__("OperationalStatus", disk["OperationalStatus"])
    return disk_stat


def getAllVolumeStatistics(conn, volumes, statAssociations, statObjectMap):
    volumeStats = []
    for v in volumes:
        volumeStat = getVolumeStatistics(conn, v, statAssociations, statObjectMap)
        if len(volumeStat) > 0:
            volumeStats += volumeStat
    logger.info("volumeStats: {0}", len(volumeStats))
    return volumeStats


def getVolumeStatistics(conn, volume, statAssociations, statObjectMap):
    volume_stat = getAssociatedStatistics(conn, volume.path, statAssociations, statObjectMap)

    if volume_stat is None or len(volume_stat) <= 0:
        volume_stat = []
        for i in range(1,1):
            try:
                volume_stat = conn.Associators(volume.path,
                                      AssocClass="CIM_ElementStatisticalData",
                                      ResultClass="CIM_BlockStorageStatisticalData")
                break
            except Exception,e:
                pass

    if len(volume_stat) > 0:
        volume_stat[0].__setitem__("uuid", volume["Name"])
        volume_stat[0].__setitem__("statID", volume["DeviceID"])
        volume_stat[0].__setitem__("OperationalStatus", volume["OperationalStatus"])
        volume_stat[0].__setitem__("BlockSize", volume["BlockSize"])
        volume_stat[0].__setitem__("ConsumableBlocks", volume["ConsumableBlocks"])
        volume_stat[0].__setitem__("NumberOfBlocks", volume["NumberOfBlocks"])

    return volume_stat


def getStorageStatisticsData(conn, path):
    stat = []
    try:
        stat = conn.Associators(path, AssocClass="CIM_ElementStatisticalData",
                                  ResultClass="CIM_BlockStorageStatisticalData")
    except Exception, e:
        logger.error("getStorageStatisticsData Error: {0}", traceback.format_exc())
    return stat


def getAssociatedStatistics(conn, path, statAssociations, statDataMap):
    for assoc in statAssociations:
        if assoc.get("ManagedElement") == path:
            return statDataMap.get(assoc.get("Stats"))
    return []


def getStatObjectMap(conn, NAMESPACE):
    stat_object_map = {}
    try:
        statObjects = conn.EnumerateInstances("CIM_BlockStorageStatisticalData",
                                            namespace=NAMESPACE, DeepInheritance=True)

        for d in statObjects:
            stat_object_map[d.path] = d
    except Exception, e:
        logger.error("trying to get statistical data found exception {1}", traceback.format_exc())

    logger.info("len(statDatas): {0}", len(stat_object_map))
    return stat_object_map


def getStatAssociations(conn, NAMESPACE):
    stat_associations = {}
    try:
        stat_associations = conn.EnumerateInstances("CIM_ElementStatisticalData",
                                    namespace=NAMESPACE, DeepInheritance=True)
    except Exception, e:
        logger.error("trying to get statistical data association found exception {1}", traceback.format_exc())

    logger.info("len(statAssociations): {0}", len(stat_associations))
    return stat_associations

def getClassNames(conn, NAMESPACE, filter):
    classNames = conn.EnumerateClassNames(namespace=NAMESPACE, DeepInheritance=True)
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
    statsService = conn.AssociatorNames(array.path,
                                        AssocClass="CIM_HostedService",
                                        ResultClass="CIM_BlockStatisticsService")

    if statsService is None or len(statsService) < 1:
        statsService = conn.AssociatorNames(array.path,
                                        AssocClass="CIM_HostedService",
                                        ResultClass="CIM_StorageConfigurationService")

    if statsService is None or len(statsService) < 1:
        logger.info('No Storage Statistics Service found')
        return None


    statsCaps = conn.Associators(statsService[0],
                                        AssocClass="CIM_ElementCapabilities",
                                        ResultClass="CIM_BlockStatisticsCapabilities")

    if statsCaps is None or len(statsCaps) < 1:
        logger.info('No Storage Statistics Capabilities found')
        return None

    logger.info('statsCaps', statsCaps[0].tomof())
    return statsCaps[0]

def detectInteropNamespace(conn):
    namespaces = ("interop", "root/interop", "pg_interop", "root/pg_interop", "root/cimv2",
                  "root/eternus", "root/hitachi/smis", "root/smis/current",
                  "root/hitachi/dm55", "root/hitachi/dm42", "root/hpmsa", "root/ema",
                  "root/tpd", "root/emc", "root/eva", "root/ibm", "root/hpq", "root")
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
                print(traceback.format_stack())

    logger.info("found the interop namespace, current namespace is {0}", conn.default_namespace)
