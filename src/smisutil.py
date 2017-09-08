# coding=utf-8
from __future__ import print_function


import string
import traceback

from pywbemReq.cim_obj import CIMInstanceName, CIMInstance
from pywbemReq.cim_operations import is_subclass
from pywbemReq.cim_types import *


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
    print('managedElements:', len(managedElements))

    arrays = []
    _operationalStatusValues = None
    for m in managedElements:
        if not is_subclass(conn, m.path.namespace, "CIM_ComputerSystem", m.classname):
            print('Array skipped because it is not a CIM_ComputerSystem')
            continue

        print('Dedicated:', m.get('Dedicated'))
        if not {15}.issubset(m.get('Dedicated')):
            print('Array skipped because it is not a block storage system')
            continue

        if not getProductInfo(conn, m):
            print('Array skipped because no vendor and/or model information found')
            continue

        if _operationalStatusValues == None:
            _operationalStatusValues = getOperationalStatusValues(conn, m, m.classname)
        status = convertOperationalStatusValues(['OperationalStatus'], _operationalStatusValues)
        m.__setitem__("OperationalStatus", status)

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


def getOperationalStatusValues(conn, ps_array, className):
    cls = conn.GetClass(className,
                        namespace=ps_array.path.namespace,
                        LocalOnly=False,
                        IncludeQualifiers=True,
                        IncludeClassOrigin=True,
                        PropertyList=['OperationalStatus'])
    ops = cls.properties.get("OperationalStatus")
    return ops.qualifiers['Values'].value


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

        if _operationalStatusValues == None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, c.classname)
        if c.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(c['OperationalStatus'], _operationalStatusValues)
            c.__setitem__("OperationalStatus", status)

        controllers.append(c)
        # print(c.tocimxml().toxml())
    return controllers


def getFcPorts(conn, ps_array, controllers):
    fcPorts = []
    if len(controllers) <= 0:
        return fcPorts

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
                for p in ports:
                    p.__setitem__("ControllerName", ct.get("ElementName"))
                fcPorts += ports
        except Exception as err:
            print("getFcPorts Error: ", err)

    if len(fcPorts) <= 0 and len(controllers) > 0:
        fcPorts = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort")
        for p in fcPorts:
            p.__setitem__("ControllerName", controllers[0].get("ElementName"))

    ports = []
    _operationalStatusValues = None
    for p in fcPorts:
        # don't include back-end ports
        usageRestriction = p.get("UsageRestriction")
        if (3 == usageRestriction):
            continue

        if (p.classname.startswith("HPEVA")):
            p.path.__delitem__("SystemName")
            p.path.__delitem__("DeviceID")
            p.path.__setitem__("Name", p.get("Name"))

        if _operationalStatusValues == None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, p.classname)
        if p.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(p['OperationalStatus'], _operationalStatusValues)
            p.__setitem__("OperationalStatus", status)

        ports.append(p)

    return ports


def getIscisiPorts(conn, ps_array, controllers):
    iscisiPorts = []
    if len(controllers) <= 0:
        return iscisiPorts

    try:
        for ct in controllers:
            ports = conn.Associators(ct.path,
                                    AssocClass="CIM_HostedAccessPoint",
                                    ResultClass="CIM_iSCSIProtocolEndpoint")
            if (ports):
                for p in ports:
                    p.__setitem__("ControllerName", ct.get("ElementName"))
                iscisiPorts += ports
    except Exception as err:
        print("getIscisiPorts Error: ", err)

    if (len(iscisiPorts) <= 0):
        iscisiPorts = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_FCPort")

        for p in iscisiPorts:
            p.__setitem__("ControllerName", controllers[0].get("ElementName"))

    _operationalStatusValues = None
    for p in iscisiPorts:
        if _operationalStatusValues == None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, p.classname)
        if p.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(p['OperationalStatus'], _operationalStatusValues)
            p.__setitem__("OperationalStatus", status)

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
        if p.get("InstanceID") == None:
            continue
        if p.get("Primordial") != False:
            continue

        if _operationalStatusValues == None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, p.classname)
        if p.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(p['OperationalStatus'], _operationalStatusValues)
            p.__setitem__("OperationalStatus", status)

        pools.append(p)
    return pools


def __getDisksFromDriveViews(conn, ps_array, controllers):
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
        # print("view", view.tomof())
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


def __getDiskDrives(conn, ps_array, controllers):
    disks = []
    try:
        disks = conn.Associators(ps_array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_DiskDrive")
        if (len(disks) == 0):
            for ct in controllers:
                diskComps = conn.Associators(ct.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_DiskDrive")
                disks += diskComps
    except:
        print(traceback.format_exc())
    return disks


def getDisks(conn, ps_array, controllers, supportedViews):
    if (supportedViews.__contains__(u"DiskDriveView")):
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

        if _operationalStatusValues == None:
            _operationalStatusValues = getOperationalStatusValues(conn, ps_array, d.classname)
        if d.has_key("OperationalStatus"):
            status = convertOperationalStatusValues(d['OperationalStatus'], _operationalStatusValues)
            d.__setitem__("OperationalStatus", status)

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
    if None != package.get("Manufacturer"):
        disk.__setitem__("Vendor", package.get("Manufacturer"))

    if None != package.get("Model"):
        disk.__setitem__("Model", package.get("Model"))

    if None != package.get("SerialNumber"):
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

    _operationalStatusValues = None
    for poolID in poolVolumeMap.keys():
        volumes = poolVolumeMap.get(poolID)

        for volume in volumes:
            volume.__setitem__('PoolID', poolID)

            if _operationalStatusValues == None:
                _operationalStatusValues = getOperationalStatusValues(conn, ps_array, volume.classname)
            if volume.has_key("OperationalStatus"):
                status = convertOperationalStatusValues(volume['OperationalStatus'], _operationalStatusValues)
                volume.__setitem__("OperationalStatus", status)

    return poolVolumeMap

def getPoolDiskMap(conn, pools, disks):
    diskExtentsMap = getDiskExtentsMap(conn, disks)

    poolDiskMap = {}
    for p in pools:
        isPrimordial = p.get("Primordial")
        if (isPrimordial == None):
            continue

        poolDisks = []
        if hasCIMClasses(conn, p.path.namespace, {"CIM_ConcreteDependency", "CIM_DiskDrive"}):

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
                        if (not diskPaths.__contains__(diskPath)):
                            diskPaths.append(diskPath)

            poolDiskMap[p.get("InstanceID")] = diskPaths
    return poolDiskMap


def getMaskingMappingViews(conn, array):
    mVolumeMappingMaskingLookup = {}
    try:
        hardwareIDMgmtServices = conn.AssociatorNames(array.path,
                                     AssocClass="CIM_HostedService",
                                     ResultClass="CIM_StorageHardwareIDManagementService")
        if None == hardwareIDMgmtServices or 0 >= len(hardwareIDMgmtServices):
            print("No hardware ID management service for storage array {0}", array.getItem("ElementName"))
            return False


        storageHarwareIDs = conn.Associators(hardwareIDMgmtServices[0],
                                     AssocClass="CIM_ConcreteDependency",
                                     ResultClass="CIM_StorageHardwareID")
        if None == storageHarwareIDs or 0 >= len(storageHarwareIDs):
            print("No hardware IDs found for storage array {0}", array.getItem("ElementName"))
            return False

        for hardwareID in storageHarwareIDs:
            views = conn.References(hardwareID.path,
                                    ResultClass="SNIA_MaskingMappingView")

            for view in views:
                # print("view",  view.tomof())
                volumeID = view.get("LogicalDevice")
                volumeMappingViews = mVolumeMappingMaskingLookup[volumeID]
                if None == volumeMappingViews:
                    volumeMappingViews = []
                    mVolumeMappingMaskingLookup[volumeID] = volumeMappingViews
                volumeMappingViews.append(view)

    except Exception, e:
        print(e)
    return mVolumeMappingMaskingLookup


def getSCSIProtocolControllers(conn, array):
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

        if None != configSvc and 0 < len(configSvc):
            # Get only SCSIProtocolControllers for this system
            SPCs = conn.Associators(configSvc[0],
                                    AssocClass="CIM_ConcreteDependency",
                                    ResultClass="CIM_SCSIProtocolController")
        if None == SPCs:
            # some use this association (conformant?)
            SPCs = conn.Associators(array.path,
                                    AssocClass="CIM_SystemDevice",
                                    ResultClass="CIM_SCSIProtocolController")

        if None == SPCs:
            # Desperate measures...Get all SCSIProtocolControllers found on the CIMOM
            SPCs = conn.EnumerateInstances("CIM_SCSIProtocolController")

        if None == SPCs or 0 >= len(SPCs):
            print("No SCSIProtocolControllers found for Storage Array \"{0}\"", array["ElementName"])
            return

        # Cache the storage hardware ID and authorized subject instances
        if None == mStorageHardwareIDLookup:
            mStorageHardwareIDLookup = {}
            objs = conn.EnumerateInstances("CIM_StorageHardwareID",
                                    namespace = array.path.namespace,
                                    DeepInheritance = True)
            for obj in objs:
                obj.path.host = array.path.host
                mStorageHardwareIDLookup[obj.path.__str__()] = obj


        if None == mAuthorizedSubjectLookup:
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
            if None != authPrivileges and 0 < len(authPrivileges):
                for ap in authPrivileges:
                    # print("ap", ap)
                    storHardwareIDs = getAssociatedEntities(ap, mAuthorizedSubjectLookup, mStorageHardwareIDLookup)
                    spc.__setitem__("storHardwareIDs", storHardwareIDs)
                    # print("storHardwareIDs", storHardwareIDs)

            # The CIM_ProtocolControllerForUnit associates a Volume to this SPC. It contains a property,
            # "DeviceNumber", that is the LUN of this association of a Volume to a Port.
            pcfuLookup = {}
            kProtocolControllerForUnitPropList = {
                "CreationClassName",
                "DeviceID",
                "SystemCreationClassName",
                "SystemName",
                "DeviceNumber"
            };
            pcfus = conn.References(spc.path,
                                        ResultClass="CIM_ProtocolControllerForUnit",
                                        Role="Antecedent",
                                        includeClassOrigin=False)
            for pcfu in pcfus:
                pcPath = pcfu.get("Antecedent")
                volumePath = pcfu.get("Dependent")
                key = pcPath.__str__() + volumePath.__str__()

                # print(pcfu.tomof())
                if not pcfuLookup.__contains__(key):
                    pcfuLookup[key] = pcfu
                    # spc.__setitem__("pcfu", pcfu)

                    spcList = mSCSIProtocolControllers.get(volumePath.__str__())
                    if None == spcList:
                        spcList = []
                        mSCSIProtocolControllers[volumePath.__str__()] = spcList
                    spcList.append(spc)

            nameFormat = spc.get("NameFormat")
            spcName = spc.get("Name")
            isISCSI = "iSCSI Name" == nameFormat or (None != spcName and spcName.__contains__("iqn"))
            print("isISCSI", isISCSI, nameFormat, spcName)
            print(spc.tomof())

            # Add FCPorts associated with the SCSIProtocolController
            # FCPort is associated to a SCSIProtocolController through
            # SAPAvailableForElement -> SCSIProtocolEndpoint -> DeviceSAPImplementation
            SPEs = conn.Associators(spc.path,
                                        AssocClass="CIM_SAPAvailableForElement",
                                        ResultClass="CIM_SCSIProtocolEndpoint")
            for spe in SPEs:
                speName= spe.get("Name")
                if isISCSI or (None != speName and speName.contains("iqn")):
                    spe.__setitem__("PermanentAddress", speName)
                    spc.__setitem__("spe", spe)
                else:
                    ports = conn.Associators(spe.path,
                                        AssocClass="CIM_DeviceSAPImplementation",
                                        ResultClass="CIM_NetworkPort")
                    if None == ports and len(ports) > 0:
                        spc.__setitem__("ports", ports)

    except Exception, e:
        print(e)
    return mSCSIProtocolControllers


def getAssociatedEntities(entity, assocs, entities):
    result = []
    for assoc in assocs.values():
        refs = assoc.values()
        found = False
        objResult = None

        if refs[0] == entity:

            objResult = entities.get(refs[1].__str__())
            if None != objResult:
                found = True

        if not found:
            if refs[1] == entity:

                objResult = entities.get(refs[0].__str__())
                if None != objResult:
                    found = True

        if found:
            result.append(objResult)

    return result


def getControllerStatistics(conn, controller, statAssociations, statObjectMap):
    controllerStat = getAssociatedStatistics(conn, controller.path, statAssociations, statObjectMap)
    # print("controllerStat", controllerStat)

    if controllerStat == None or len(controllerStat) <= 0:
        try:
            controllerStat = getStorageStatisticsData(conn, controller.path)
        except:
            pass

    if len(controllerStat) > 0:
        controllerStat[0].__setitem__("statID", controller["ElementName"].upper())
        controllerStat[0].__setitem__("OperationalStatus", controller["OperationalStatus"])
    return controllerStat


def getPortStatistics(conn, port, statAssociations, statObjectMap):
    portStat = getAssociatedStatistics(conn, port.path, statAssociations, statObjectMap)

    if portStat == None or len(portStat) <= 0:
        # print("port.path: ", port.path)
        portStat = getStorageStatisticsData(conn, port.path)

    if len(portStat) > 0:
        portStat[0].__setitem__("statID", port["PermanentAddress"])
        portStat[0].__setitem__("OperationalStatus", port["OperationalStatus"])
        portStat[0].__setitem__("Speed", port["Speed"])
        if port.has_key("MaxSpeed"):
            portStat[0].__setitem__("MaxSpeed", port["MaxSpeed"])
    return portStat


def getDiskStatistics(conn, disk, statAssociations, statObjectMap):
    diskStat = []
    onMedia = False     #TODO if stats for disks are associated with the media on this SMI provider

    if (not onMedia):
        diskStat = getAssociatedStatistics(conn, disk.path, statAssociations, statObjectMap)
        if diskStat == None or len(diskStat) <= 0:
            diskStat = getStorageStatisticsData(conn, disk.path)

    if diskStat == None or len(diskStat) <= 0:
        medias = conn.AssociatorNames(disk.path,
                                      AssocClass="CIM_MediaPresent",
                                      ResultClass="CIM_StorageExtent")
        if (len(medias) > 0):
            diskStat = getAssociatedStatistics(conn, medias[0], statAssociations, statObjectMap)
            if diskStat == None or len(diskStat) <= 0:
                diskStat = getStorageStatisticsData(conn, medias[0])

    if len(diskStat) > 0:
        diskStat[0].__setitem__("statID", disk["DeviceID"].upper())
        diskStat[0].__setitem__("OperationalStatus", disk["OperationalStatus"])
    return diskStat


def getVolumeStatistics(conn, volume, statAssociations, statObjectMap):
    volumeStat = getAssociatedStatistics(conn, volume.path, statAssociations, statObjectMap)

    if volumeStat == None or len(volumeStat) <= 0:
        volumeStat = conn.Associators(volume.path,
                                      AssocClass="CIM_ElementStatisticalData",
                                      ResultClass="CIM_BlockStorageStatisticalData",
                                      IncludeClassOrigin=True)

    if len(volumeStat) > 0:
        volumeStat[0].__setitem__("statID", volume["DeviceID"])
        volumeStat[0].__setitem__("OperationalStatus", volume["OperationalStatus"])
        volumeStat[0].__setitem__("BlockSize", volume["BlockSize"])
        volumeStat[0].__setitem__("ConsumableBlocks", volume["ConsumableBlocks"])
        volumeStat[0].__setitem__("NumberOfBlocks", volume["NumberOfBlocks"])

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


def getStatsCapabilities(conn, array):
    statsService = conn.AssociatorNames(array.path,
                                        AssocClass="CIM_HostedService",
                                        ResultClass="CIM_BlockStatisticsService")

    if None == statsService or len(statsService) < 1:
        statsService = conn.AssociatorNames(array.path,
                                        AssocClass="CIM_HostedService",
                                        ResultClass="CIM_StorageConfigurationService")

    if None == statsService or len(statsService) < 1:
        print('No Storage Statistics Service found')
        return None


    statsCaps = conn.Associators(statsService[0],
                                        AssocClass="CIM_ElementCapabilities",
                                        ResultClass="CIM_BlockStatisticsCapabilities")

    if None == statsCaps or len(statsCaps) < 1:
        print('No Storage Statistics Capabilities found')
        return None

    print('statsCaps', statsCaps[0].tomof())
    return statsCaps[0]