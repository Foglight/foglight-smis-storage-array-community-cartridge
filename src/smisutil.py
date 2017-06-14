# coding=utf-8
from __future__ import print_function


import string

from pywbemReq.cim_obj import CIMInstanceName, CIMInstance
from pywbemReq.cim_operations import is_subclass


def getRegisteredProfiles(conn):
    kProfilePropList = ["InstanceID", "RegisteredVersion", "RegisteredName"]
    profiles = conn.EnumerateInstances("CIM_RegisteredProfile", DeepInheritance=True, PropertyList=kProfilePropList)
    return profiles

def getElementsForProfile(conn, profileName):
    profiles = getRegisteredProfiles(conn)
    profiles = [p for p in profiles if p.get("RegisteredName") == profileName]
    profiles = profiles[:1]
    print('profiles:', len(profiles))

    elements = []
    for p in profiles:
        managedElements = conn.Associators(p.path,
                                AssocClass="CIM_ElementConformsToProfile",
                                Role="ConformantStandard",
                                ResultRole="ManagedElement")
        for managedElement in managedElements:
            if (managedElement.get("ElementName") == None or managedElement.get("ElementName") == ""):
                managedElement.__setitem__("ElementName", managedElement.get("Name"))
            elements.append(managedElement)
    return elements;

def getArray(conn):
    managedElements = getElementsForProfile(conn, "Array")
    print("managedElements: ", len(managedElements))
    ps_array = managedElements[0]
    getProductInfo(conn, ps_array)
    return ps_array


def getArrays(conn):
    managedElements = getElementsForProfile(conn, "Array")

    arrays = []
    for m in managedElements:
        if not is_subclass(conn, m.path.namespace, "CIM_ComputerSystem", m.classname):
            continue

        if not {3, 15}.issubset(m.get('Dedicated')):
            continue

        if not getProductInfo(conn, m):
            continue

        arrays.append(m)
    return arrays


def getProductInfo(conn, ps_array):
    physpacks = conn.Associators(ps_array.path,
                                AssocClass="CIM_SystemPackaging",
                                ResultClass="CIM_PhysicalPackage")
    if None == physpacks:
        return False

    useChassis = None
    if (len(physpacks) == 1):
        useChassis = physpacks[0]
    else:
        for p in physpacks:
            packageType = p.get("ChassisPackageType")
            if ("22" == packageType or "17" == packageType):
                useChassis = p
                break
        if (None == useChassis):
            useChassis = physpacks[0]

    products = conn.Associators(useChassis.path,
                                AssocClass="CIM_ProductPhysicalComponent",
                                ResultClass="CIM_Product")
    if None == products:
        return False


    model = useChassis.get("Model")
    if (None != model):
        model = string.replace(model, "Rack Mounted ", "")
        model = string.replace(model, '_', '-')
        ps_array.__setitem__("Model", model)

    product = products[0]
    vendor = product.get("Vendor")
    if (None != vendor):
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
    if (isBlockStorageViewsSupported):
        viewCaps = getViewCapabilities(conn, ps_array)
    if (len(viewCaps) > 0):
        supportedViews = viewCaps[0].get("SupportedViews")
    return supportedViews


def getControllers(conn, ps_array):
    controllers = []
    comps = conn.Associators(ps_array.path,
                                AssocClass="CIM_ComponentCS",
                                ResultClass="CIM_ComputerSystem",
                                Role="GroupComponent",
                                ResultRole="PartComponent")

    arrayClassName = ps_array.classname
    for c in comps:
        # EMC Clariion and Symmetrix have front-end FC ports on EMC_StorageProcessorSystem Class
        if ((arrayClassName.startswith("Clar") or arrayClassName.startswith("Symm"))
                and not c.classname.__contains__("StorageProcessorSystem")):
            continue
        if (c.classname.lower().__contains__("nodepairsystem")):
            continue

        if (c.classname.startswith("HPEVA")):
            c.path.__delitem__("Name")
            c.path.__setitem__("ElementName", c.get("ElementName"))


        softwareIdentities = conn.Associators(c.path, AssocClass="CIM_InstalledSoftwareIdentity",
                                               ResultClass="CIM_SoftwareIdentity");
        if (softwareIdentities != None and len(softwareIdentities) > 0 and softwareIdentities[0] != None):
            versionString = softwareIdentities[0].get("VersionString")
            c.__setitem__("VersionString", versionString)

        controllers.append(c)
    return controllers


def getFcPorts(conn, ps_array, controllers):
    fcPorts = []
    for ct in controllers:
        try:
            ports = conn.Associators(ct.path, AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort",
                                    Role="GroupComponent",
                                    ResultRole="PartComponent")

            if (None == ports or  len(ports) <= 0):
                print("No FC ports found for %s using %s" % (ct.get("ElementName"),  conn) )
                controllers.remove(ct)
            else:
                fcPorts += ports
        except Exception as err:
            print("getFcPorts Error: ", err)

    if (len(fcPorts) <= 0):
        fcPorts = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort")

    for p in fcPorts:
        usageRestriction = p.get("UsageRestriction")

        # don't include back-end ports
        if (3 == usageRestriction):
            fcPorts.remove(p)
            continue

        if (p.classname.startswith("HPEVA")):
            p.path.__delitem__("SystemName")
            p.path.__delitem__("DeviceID")
            p.path.__setitem__("Name", p.get("Name"))

    return fcPorts


def getIscisiPorts(conn, ps_array, controllers):
    iscisiPorts = []
    try:
        for ct in controllers:
            ports = conn.Associators(ct.path,
                                    AssocClass="CIM_HostedAccessPoint",
                                    ResultClass="CIM_iSCSIProtocolEndpoint")
            if (ports): iscisiPorts += ports
    except Exception as err:
        print("getIscisiPorts Error: ", err)

    if (len(iscisiPorts) <= 0):
        iscisiPorts = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort")
    return iscisiPorts


def getExtents(conn, ps_array, controllers):
    extents = conn.Associators(ps_array.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_StorageExtent")
    if (len(extents) == 0):
        for ct in controllers:
            extentComps = conn.Associators(ct.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_StorageExtent")
            extents += extentComps
    return extents


def getPools(conn, ps_array):
    spools = conn.Associators(ps_array.path,
                                AssocClass="CIM_HostedStoragePool",
                                ResultClass="CIM_StoragePool")

    pools = []
    for p in spools:
        if p.get("InstanceID") == None:
            continue
        if p.get("Primordial") != False:
            continue
        pools.append(p)
    return pools


def getDisksFromDriveViews(conn, ps_array, controllers):
    disks = []
    diskViews = conn.Associators(ps_array.path,
                                AssocClass="SNIA_SystemDeviceView",
                                ResultClass="SNIA_DiskDriveView")
    if None == diskViews or len(diskViews) <=0:
        diskViews = []
        for ct in controllers:
            compViews = conn.Associators(ct.path,
                                AssocClass="SNIA_SystemDeviceView",
                                ResultClass="SNIA_DiskDriveView")
            if None != compViews and len(compViews) > 0:
                diskViews += compViews

    for view in diskViews:
        # pull the keys specific to the storage volume from the view of the volume
        creationClassName = view.get("DDCreationClassName")
        v = CIMInstance(classname=creationClassName)
        v.path = CIMInstanceName(classname=creationClassName, namespace=ps_array.path.namespace)
        unsupportedPropertyNames = ()

        for k in view.keys():
            if k.startswith('DD') and k not in unsupportedPropertyNames and None != view.get(k):
                v.__setitem__(k[2:], view.get(k))

        for k in view.path.keys():
            if k.startswith('DD') and None != view.get(k):
                v.path.__setitem__(k[2:], view.get(k))

        disks.append(v)
    return disks


def getDiskDrives(conn, ps_array, controllers):
    disks = conn.Associators(ps_array.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_DiskDrive")
    if (len(disks) == 0):
        for ct in controllers:
            diskComps = conn.Associators(ct.path,
                                AssocClass="CIM_SystemDevice",
                                ResultClass="CIM_DiskDrive")
            disks += diskComps
    return disks


def getDisks(conn, ps_array, controllers, supportedViews):
    if (supportedViews.__contains__(u"DiskDriveView")):
        disks = getDisksFromDriveViews(conn, ps_array, controllers)
    else:
        disks = getDiskDrives(conn, ps_array, controllers)
    return disks


def __getVolumesFromVolumeViews(conn, ps_array):
    poolVolumeMap = {}
    try:
        volumeViews = conn.Associators(ps_array.path,
                                AssocClass="SNIA_SystemDeviceView",
                                ResultClass="SNIA_VolumeView")
    except Exception as e:
        print(e)

    for view in volumeViews:
        # pull the keys specific to the storage volume from the view of the volume
        v = CIMInstance(classname=view.get("SVCreationClassName"))
        v.path = CIMInstanceName(classname=view.get("SVCreationClassName"), namespace=ps_array.path.namespace)
        unsupportedPropertyNames = ('SVPrimordial', 'SVNoSinglePointOfFailure',
                                    'SVIsBasedOnUnderlyingRedundancy', 'SVClientSettableUsage')
        for k in view.keys():
            if k.startswith('SV') and k not in unsupportedPropertyNames and None != view.get(k):
                v.__setitem__(k[2:], view.get(k))

        for k in view.path.keys():
            if k.startswith('SV') and None != view.get(k):
                v.path.__setitem__(k[2:], view.get(k))

        poolID = view.get("SPInstanceID")
        volumes = poolVolumeMap.get(poolID);
        if (volumes == None):
            volumes = []
            poolVolumeMap[poolID] = volumes
        volumes.append(v)
    return poolVolumeMap


def __getVolumesFromPools(conn, pools):
    poolVolumeMap = {}
    for p in pools:
        vols = []
        try:
            vols = conn.Associators(p.path,
                            AssocClass="CIM_AllocatedFromStoragePool",
                            ResultClass="CIM_StorageVolume")
        except Exception as e:
            print(e)

        poolID = p.get("InstanceID")
        volumes = poolVolumeMap.get(poolID);
        if (volumes == None):
            volumes = []
            poolVolumeMap[poolID] = volumes
        volumes += vols
    return poolVolumeMap


def getPoolVolumesMap(conn, ps_array, pools, supportedViews):
    poolVolumeMap = {}
    # Do not allow VolumeViews for Hitachi - they do not provide the necessary attributes in the VolumeView class:
    # specifically "ThinlyProvisioned" and "IsComposite"
    if (supportedViews.__contains__(u"VolumeView") and not ps_array.classname.startswith("HITACHI")):
        poolVolumeMap = __getVolumesFromVolumeViews(conn, ps_array)
    if (len(poolVolumeMap) <= 0):
        poolVolumeMap = __getVolumesFromPools(conn, pools)

    for poolID in poolVolumeMap.keys():
        volumes = poolVolumeMap.get(poolID)
        for volume in volumes:
            volume.__setitem__('PoolID', poolID)
    return poolVolumeMap

def getPoolDiskMap(conn, pools):
    poolDiskMap = {}
    for p in pools:
        isPrimordial = p.get("Primordial")
        if (isPrimordial == None):
            continue
        if hasCIMClasses(conn, p.path.namespace, {"CIM_ConcreteDependency", "CIM_DiskDrive"}):
        # if (p.classname.startswith("Clar_") or p.classname.startswith("Symm_")):
            poolDisks = conn.AssociatorNames(p.path,
                            AssocClass="CIM_ConcreteDependency",
                            ResultClass="CIM_DiskDrive",
                            Role="Dependent",
                            ResultRole="Antecedent")
            poolDiskMap[p.get("InstanceID")] = poolDisks
        # elif p.classname.startswith("HPEVA_"):
        else:
            poolDiskExtents = conn.AssociatorNames(p.path,
                            AssocClass="CIM_ConcreteComponent",
                            ResultClass="CIM_StorageExtent",
                            Role="GroupComponent",
                            ResultRole="PartComponent")
            poolDiskMap[p.get("InstanceID")] = poolDiskExtents
    return poolDiskMap


def getControllerStatistics(conn, controller_path, statAssociations, statObjectMap):
    controllerStat = getAssociatedStatistics(conn, controller_path, statAssociations, statObjectMap)
    # print("controllerStat", controllerStat)

    if controllerStat == None or len(controllerStat) <= 0:
        try:
            controllerStat = getStorageStatisticsData(conn, controller_path)
        except:
            pass
    return controllerStat


def getPortStatistics(conn, port_path, statAssociations, statObjectMap):
    portStat = getAssociatedStatistics(conn, port_path, statAssociations, statObjectMap)

    if portStat == None or len(portStat) <= 0:
        # print("port.path: ", port.path)
        portStat = getStorageStatisticsData(conn, port_path)
    return portStat


def getDiskStatistics(conn, disk_path, statAssociations, statObjectMap):
    diskStat = []
    onMedia = False     #TODO if stats for disks are associated with the media on this SMI provider

    if (not onMedia):
        diskStat = getAssociatedStatistics(conn, disk_path, statAssociations, statObjectMap)
        if diskStat == None or len(diskStat) <= 0:
            diskStat = getStorageStatisticsData(conn, disk_path)

    if diskStat == None or len(diskStat) <= 0:
        medias = conn.AssociatorNames(disk_path,
                                      AssocClass="CIM_MediaPresent",
                                      ResultClass="CIM_StorageExtent")
        if (len(medias) > 0):
            diskStat = getAssociatedStatistics(conn, medias[0], statAssociations, statObjectMap)
            if diskStat == None or len(diskStat) <= 0:
                diskStat = getStorageStatisticsData(conn, medias[0])
    return diskStat


def getVolumeStatistics(conn, volume_path, statAssociations, statObjectMap):
    volumeStat = getAssociatedStatistics(conn, volume_path, statAssociations, statObjectMap)

    if volumeStat == None or len(volumeStat) <= 0:
        volumeStat = conn.Associators(volume_path,
                                      AssocClass="CIM_ElementStatisticalData",
                                      ResultClass="CIM_BlockStorageStatisticalData",
                                      IncludeClassOrigin=True)
    return volumeStat


def getStorageStatisticsData(conn, path):
    stat = []
    try:
        stat = conn.Associators(path, AssocClass="CIM_ElementStatisticalData",
                                  ResultClass="CIM_BlockStorageStatisticalData")
    except Exception, e:
        print("getStorageStatisticsData Error: ", e)
    return stat


def getAssociatedStatistics(conn, path, statAssociations, statDataMap):
    for assoc in statAssociations:
        if (assoc.get("ManagedElement") == path):
            return statDataMap.get(assoc.get("Stats"))
    return []


def getStatObjectMap(conn, NAMESPACE):
    statObjects = conn.EnumerateInstances("CIM_BlockStorageStatisticalData",
                                        namespace=NAMESPACE, DeepInheritance=True)
    statObjectMap = {}
    for d in statObjects:
        statObjectMap[d.path] = d
    return statObjectMap


def getStatAssociations(conn, NAMESPACE):
    statAssociations = conn.EnumerateInstances("CIM_ElementStatisticalData",
                                    namespace=NAMESPACE, DeepInheritance=True)
    return statAssociations


def getClassNames(conn, NAMESPACE, filter):
    classNames = conn.EnumerateClassNames(namespace=NAMESPACE, DeepInheritance=True)
    if (filter):
        classNames = [c for c in classNames if filter(c)]
    return sorted(classNames)


def getBlockStorageViewsSupported(conn):
    profiles = conn.EnumerateInstances("CIM_RegisteredProfile")
    profiles = [s for s in profiles if s.get("RegisteredName") == 'Block Storage Views']

    subprofiles = conn.EnumerateInstances("CIM_RegisteredSubprofile")
    subprofiles = [s for s in subprofiles if s.get("RegisteredName") == 'Block Storage Views']

    isBlockStorageViewsSupported = len(profiles) > 0 or len(subprofiles) > 0
    return isBlockStorageViewsSupported


def hasStatisticalDataClass(conn, __namespace):
    CLASS_NAMES = getClassNames(conn, __namespace, None)
    return (CLASS_NAMES.__contains__("CIM_ElementStatisticalData")
        and CLASS_NAMES.__contains__("CIM_BlockStorageStatisticalData"))


def hasCIMClasses(conn, __namespace, classNames):
    CLASS_NAMES = getClassNames(conn, __namespace, None)
    return classNames.issubset(CLASS_NAMES)



# def getDiskPathsFromDriveViews(conn, ps_array, controllers):
#     diskPaths = []
#     diskViewPaths = conn.AssociatorNames(ps_array.path,
#                                 AssocClass="SNIA_SystemDeviceView",
#                                 ResultClass="SNIA_DiskDriveView")
#     if None == diskViewPaths or len(diskViewPaths) <=0:
#         diskViewPaths = []
#         for ct in controllers:
#             compViews = conn.AssociatorNames(ct.path,
#                                 AssocClass="SNIA_SystemDeviceView",
#                                 ResultClass="SNIA_DiskDriveView")
#             if None != compViews and len(compViews) > 0:
#                 diskViewPaths += compViews
#
#     for viewPath in diskViewPaths:
#         # pull the keys specific to the storage volume from the view of the volume
#         creationClassName = viewPath.get("DDCreationClassName")
#         diskPath = CIMInstanceName(classname=creationClassName, namespace=ps_array.path.namespace)
#
#         for k in viewPath.keys():
#             if k.startswith('DD') and None != viewPath.get(k):
#                 diskPath.__setitem__(k[2:], viewPath.get(k))
#
#         diskPaths.append(diskPath)
#     return diskPaths
#
#
# def getDiskDrivePaths(conn, ps_array, controllers):
#     diskPaths = conn.AssociatorsNames(ps_array.path,
#                                 AssocClass="CIM_SystemDevice",
#                                 ResultClass="CIM_DiskDrive")
#     if (len(diskPaths) == 0):
#         for ct in controllers:
#             diskComps = conn.AssociatorNames(ct.path,
#                                 AssocClass="CIM_SystemDevice",
#                                 ResultClass="CIM_DiskDrive")
#             diskPaths += diskComps
#     return diskPaths
#
#
# def getDiskPaths(conn, ps_array, controllers, supportedViews):
#     if (supportedViews.__contains__(u"DiskDriveView")):
#         diskPaths = getDiskPathsFromDriveViews(conn, ps_array, controllers)
#     else:
#         diskPaths = getDiskDrivePaths(conn, ps_array, controllers)
#     return diskPaths