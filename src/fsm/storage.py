#  Copyright 2016 Dell Inc.
#  ALL RIGHTS RESERVED.
#
#  This file is provided for demonstration and educational uses only.
#  Permission to use, copy, modify and distribute this file for
#  any purpose and without fee is hereby granted, provided that the
#  above copyright notice and this permission notice appear in all
#  copies, and that the name of Dell not be used in
#  advertising or publicity pertaining to this material without
#  the specific, prior written permission of an authorized
#  representative of Dell Inc.
#
#  DELL INC. MAKES NO REPRESENTATIONS OR WARRANTIES ABOUT
#  THE SUITABILITY OF THE SOFTWARE EITHER EXPRESS OR IMPLIED,
#  INCLUDING BUT NOT LIMITED TO THE IMPLIED WARRANTIES OF
#  MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR
#  NON-INFRINGEMENT. DELL SHALL NOT BE LIABLE FOR ANY
#  DAMAGES SUFFERED BY USERS AS A RESULT OF USING, MODIFYING
#  OR DISTRIBUTING THIS OR ITS DERIVATIVES.


"""
Classes for creating and population the data model which is used to represent storage arrays
(and eventually switches).

**NOTE**: Start with :class:`SanNasModel` as the single base class of the collection, and
use its methods to create all the sub elements needed.
"""

import datetime
import os
import shelve

import foglight.topology
import foglight.logging
import foglight.utils

import fsm.rollups

from java.lang import Long
from java.util import ArrayList
from java.util.concurrent import TimeUnit

_logger = foglight.logging.get_logger("fsm-data-wrapper")


def _timedelta2milliseconds(td):
    return TimeUnit.DAYS.toMillis(td.days) + \
           TimeUnit.SECONDS.toMillis(td.seconds) + \
           TimeUnit.MICROSECONDS.toMillis(td.microseconds)


class SanNasModel(object):
    """
    Main encapsulation class for storage array data collections.

    There will only ever be a single SanNasModel created into which all
    other classes are stored and retrieved. All updates and performance data
    should be applied to this classes and the related classes to ensure that it
    is correctly formatted and correlated for using in the existing Foglight
    dashboards.

    :param topology_update: The topology update in progress or None
    :type topology_update: :class:`foglight.topology.TopologyUpdateTransaction` | None
    :param data_update: The data update in progress or None
    :type data_update: :class:`foglight.topology.TopologyDataCollection` | None
    """

    def __init__(self, topology_update=None, data_update=None):
        # At least one is required
        if topology_update is None and data_update is None:
            raise ValueError('Exactly one of topology_update or data_update must be specified')
        elif topology_update is not None and data_update is not None:
            raise ValueError('Exactly one of topology_update or data_update must be specified')

        self.__topology_update = topology_update
        self.__data_update = data_update

        # If we're doing a topology update, then we should create a new object
        # If we're doing a data update, then we should get the one and only
        #    instance of the SanNasModel in the service.
        # Everything else we submit is based off of this root container.

        if self.__topology_update:
            self.__model = self.__topology_update.create_object("SanNasModel",
                                                                {"name": "SanNasModel"})
            # And the top level container objects
            self.__arrays = self.__topology_update.create_object("SanStorageArrays",
                                                                 {"name": "SanStorageArrays"})
            self.__model.set_property("storageArrays", self.__arrays.key)

            self.__filers = self.__topology_update.create_object("SanFilers",
                                                                 {"name": "SanFilers"})
            self.__model.set_property("filers", self.__filers.key)

            self.__fabrics = self.__topology_update.create_object("SanFabrics",
                                                                  {"name": "SanFabrics"})
            self.__model.set_property("fabrics", self.__fabrics.key)

            self.__switches = self.__topology_update.create_object("SanFcSwitches",
                                                                   {"name": "SanFcSwitches"})
            self.__model.set_property("fcSwitches", self.__switches.key)

            for array in self.__arrays.get_property("storageArrays", []):
                try:
                    array = self.__topology_update.get_object(array)
                except:
                    continue

                for group in ["pools", "physicalDisks", "luns", "controllers"]:
                    # The values we're submitted for these are the only ones we want
                    # displayed in the server.
                    array.mark_property_for_replacement(group)

        else:
            key = foglight.topology.make_object_key("SanNasModel",
                                                    {"name": "SanNasModel"})
            self.__model = self.__data_update.get_object(key)

            # And the top level container objects
            key = foglight.topology.make_object_key("SanStorageArrays",
                                                    {"name": "SanStorageArrays"})
            self.__arrays = self.__data_update.get_object(key)

            key = foglight.topology.make_object_key("SanFilers",
                                                    {"name": "SanFilers"})
            self.__filers = self.__data_update.get_object(key)

            key = foglight.topology.make_object_key("SanFabrics",
                                                    {"name": "SanFabrics"})
            self.__fabrics = self.__data_update.get_object(key)

            key = foglight.topology.make_object_key("SanFcSwitches",
                                                    {"name": "SanFcSwitches"})
            self.__switches = self.__data_update.get_object(key)

    def get_storage_array(self, device_id, vendor):
        """
        Creates a new SanStorageArray, or obtains an existing one. The combination
        of `device_id` and `vendor` must be globally unique.

        Instances can only be created during the inventory phase. During the performance
        collection phase only previously discovered items can be referenced.

        :param device_id: the ID for the array (serial number, name, etc)
        :type device_id: str
        :param vendor: The name of the array vendor
        :type vendor: str
        :return: :class:`SanStorageArray`
        """
        #  Check to see if we've got an existing object
        idprops = {"deviceID": device_id, "vendorName": vendor}

        if self.__data_update:
            key = foglight.topology.make_object_key("SanStorageArray", idprops)
            try:
                array = self.__data_update.get_object(key)
            except:
                _logger.warn("Can't submit data for an array not discovered "
                             "during the inventory phase: {0}/{1}"
                             .format(device_id, vendor))
                return None
        else:
            # Nope, we have to create one
            array = self.__topology_update.create_object("SanStorageArray", idprops)

            # Need at least one property set on the object or it will not be submitted
            array.set_property("name", "Unnamed SanStorageArray")

            iscsi_ports = self.__topology_update.create_object("SanStorageSupplierPorts",
                                                               {
                                                                   "name": "ISCSI",
                                                                   "parent": array.key
                                                                })
            iscsi_ports.mark_property_for_replacement("ports")
            array.set_property("iSCSi_ports", iscsi_ports.key)

            fc_ports = self.__topology_update.create_object("SanStorageSupplierPorts",
                                                            {
                                                                "name": "FC",
                                                                "parent": array.key
                                                            })
            fc_ports.mark_property_for_replacement("ports")
            array.set_property("FC_ports", fc_ports.key)

            array.set_property("monitoringAgent", self.__get_monitoring_agent_key())

            # And add it to the model in the correct location

            # type = List<key for SanStorageArray>
            arrays = self.__arrays.get_property("storageArrays", ArrayList())

            if not arrays.contains(array.key):
                arrays.add(array.key)
                self.__arrays.set_property("storageArrays", arrays)

        return SanStorageArray(array, self.__model, self.__topology_update, self.__data_update)

    def submit(self,
               inventory_frequency=datetime.timedelta(),
               performance_frequency=datetime.timedelta()):
        """
        Submits the current state of the data model.

        :param inventory_frequency: How often inventory/topology data is expected to be collected,
                 if known.
        :type inventory_frequency: datetime.timedelta
        :param performance_frequency: How often performance data is expected to be collected,
                 if known.
        :type performance_frequency: datetime.timedelta

        """

        agent_key = self.__get_monitoring_agent_key()

        if self.__topology_update:
            timestamps = self.__topology_update.create_object("SanDataSubmissionFrequency",
                                                              {"agent": agent_key})

            timestamps.set_property("topologyFrequency",
                                    Long(_timedelta2milliseconds(inventory_frequency)))
            timestamps.set_property("performanceFrequency",
                                    Long(_timedelta2milliseconds(performance_frequency)))

            # todo The timestamp of the topology observation needs to be cached and submitted later
            self.__apply_timestamps(self.__topology_update, timestamps)

        else:
            timestamp_key = foglight.topology.make_object_key("SanDataSubmissionFrequency",
                                                              {"agent": agent_key})
            timestamps = self.__data_update.get_object(timestamp_key)

            timestamps.set_observation_value("lastPerformanceCollection",
                                             foglight.utils.datetime2javadate(datetime.datetime.now()))

            # See if this is being tracked or not
            location = foglight.get_version_specific_directory()
            filename = os.path.join(location, "collection-tracker")

            _logger.debug("Checking for last topology timestamp in {0}.dat".format(filename))
            if os.path.exists(filename + ".dat"):
                state_store = shelve.open(filename)
                ts = state_store.get('last_inventory')
                state_store.close()

                if ts:
                    timestamps.set_observation_value("lastTopologyCollection",
                                                     foglight.utils.datetime2javadate(ts))

            self.__model.set_frequency(performance_frequency)

        # Rollups and logging
        self.__post_process(performance_frequency)

        if self.__topology_update:

            self.__topology_update.submit(on_success=self.__submit_success)
        else:
            self.__data_update.submit(on_success=self.__submit_success)

    def __submit_success(self, key):
        if self.__topology_update:
            _logger.info("Submission succeeded: (extra: {0}). Committing the results.", str(key))
            self.__topology_update.commit()

            # Data/performance updates do not need to be committed as they do  not affect
            # the structure of the topology model.

    def __apply_timestamps(self, update, timestamps):
        for key in self.__arrays.get_property("storageArrays", []):
            obj = update.get_object(key)
            obj.set_property("submissionFrequency", timestamps.key)

        for key in self.__filers.get_property("filers", []):
            obj = update.get_object(key)
            obj.set_property("submissionFrequency", timestamps.key)

        for key in self.__switches.get_property("fcSwitches", []):
            obj = update.get_object(key)
            obj.set_property("submissionFrequency", timestamps.key)

        for key in self.__fabrics.get_property("fabrics", []):
            obj = update.get_object(key)
            obj.set_property("submissionFrequency", timestamps.key)

    def __get_monitoring_agent_key(self):
        if self.__topology_update:
            agent = self.__topology_update.create_object("SanStorageCollectorAgent2",
                                                         {"agentID": 0})
            return agent.key
        else:
            return foglight.topology.make_object_key("SanStorageCollectorAgent2",
                                                     {"agentID": 0})

    def __post_process(self, frequency):
        """
        Performance: post processing and rollups.
        Inventory: summary logging only
        """
        if self.__topology_update:
            fsm.rollups.topology_post_processor(self.__topology_update, self.__model)
        else:
            fsm.rollups.performance_post_processor(self.__data_update, self.__model, frequency)


class _SanKeyedItem(object):
    """
    Base class for all submitted topology items
    """

    def __init__(self, delegate):
        self.__delegate = delegate

    def _key(self):
        return self.__delegate.key


class _SanTopologyItem(_SanKeyedItem):
    """
    Base class for all submitted topology items that allow UI label overrides
    """

    def __init__(self, delegate):
        _SanKeyedItem.__init__(self, delegate)
        self.__delegate = delegate

    def set_label(self, label):
        """
        Changes the label that is used for this item in the UI. There are defaults provided for
        all type, but these can be changed to more accurately reflect the
        item being monitored. For example, a "Pool" could be "Tier" or "Aggregate"

        This value is *aggressively* cached in the UI and it may take up to 10 minutes
        before the new value is displayed.

        The name should be singular ("Pool", not "Pools") and will be automatically
        pluralized when needed.

        .. note:: This can only be done during an **inventory/topology** update

        :param label:
        :type label: str
        """
        self.__delegate.set_property("labelOverride", label)


class SanStorageArray(_SanTopologyItem):
    """
    Main class for storage arrays.

    The instances of this class must be obtained via the
    :func:`SanNasModel.get_storage_array()` method. Directly creating this class is not
    supported

    :param delegate: The delegate from the managed topology service we deal with
    :type delegate: :class:`foglight.topology.TopologyObjectUpdate` |
                    :class:`foglight.topology.TopologyObjectData`
    :param model: The SanNasModel we use for creating sub objects
    :type model: :class:`SanNasModel`
    :param topology_update: The topology update in progress or None
    :type topology_update: :class:`foglight.topology.TopologyUpdateTransaction` | None
    :param data_update: The data update in progress or None
    :type data_update: :class:`foglight.topology.TopologyDataCollection` | None
    """

    def __init__(self, delegate, model, topology_update=None, data_update=None):
        _SanTopologyItem.__init__(self, delegate)
        self.__delegate = delegate
        self.__model = model
        self.__topology_update = topology_update
        self.__data_update = data_update

    def set_name(self, name):
        """
        Sets a human readable name for the array. Optional but *strongly* recommended. This is
        often the host name of the array or its management host.

        .. note:: This can only be done during an **inventory/topology** update

        :param name: The human readable name of the array
        :type name: str
        """

        self.__delegate.set_property("name", name)

    def set_product_name(self, name):
        """
        Sets a human readable product name for the array. Optional but *strongly* recommended

        .. note:: This can only be done during an **inventory/topology** update

        :param name: The human readable product name of the array
        :type name: str
        """

        self.__delegate.set_property("productName", name)

    def set_model(self, model):
        """
        Sets a model number the array. Optional.

        .. note:: This can only be done during an **inventory/topology** update

        :param model: Model name or number
        :type model: str
        """

        self.__delegate.set_property("modelNumber", model)

    def _create_item(self, type_name, id_props, container, container_property):

        if self.__data_update:
            key = foglight.topology.make_object_key(type_name, id_props)
            try:
                obj = self.__data_update.get_object(key)
            except:
                ids = ''.join('{}: {}, '.format(key, val) for key, val in sorted(id_props.items()))
                _logger.warn("Cannot submit data for {0} not discovered during "
                             "the inventory phase. ({1})" .format(type_name, ids))
                return None
        else:
            # We have to create it ourselves, and hook it up to the storage supplier
            obj = self.__topology_update.create_object(type_name, id_props)

            # Need at least one property set on the object or it will not be submitted
            if "name" not in id_props:
                obj.set_property("name", "Unnamed " + type_name)

            # The list of objs in the storage supplier will contain this new obj
            objs = container.get_property(container_property, ArrayList())

            if not objs.contains(obj.key):
                objs.add(obj.key)

            container.set_property(container_property, objs)

        return obj

    def get_physical_disk(self, device_id):
        """
        Create or obtains a SanPhysicalDisk instance. Instances can only be created during
        the inventory phase. During the performance collection phase only previously
        discovered items can be referenced.

        :param device_id: Globally unique ID for this disk. A human readable name can
           be set with :func:`SanPhysicalDisk.set_property()` if desired
        :type device_id: str
        :return: :class:`SanPhysicalDisk` | :any:`None`
        """

        id_props = {
            "deviceID": device_id,
            # A disk has a property that points to the storage supplier
            # it is associated with
            "storageSupplier": self.__delegate.key
        }

        disk = self._create_item("SanPhysicalDisk", id_props, self.__delegate, "physicalDisks")
        if not disk:
            # already logged
            return None

        if self.__topology_update:
            # Default unless the disk is associated with a controller.
            disk.set_property("hasParentController", False)

        return SanPhysicalDisk(disk, self.__topology_update, self.__data_update)

    def get_lun(self, device_id):
        """
        Create or obtains a SanLun instance. Instances can only be created during
        the inventory phase. During the performance collection phase only previously
        discovered items can be referenced.

        :param device_id: Globally unique ID for this LUN. A human readable name can
           be set with :func:`SanLun.set_property()` if desired
        :type device_id: str
        :return: :class:`SanLun` | :any:`None`
        """

        id_props = {
            "deviceID": device_id,
            # A LUN has a property that points to the storage supplier
            # it is associated with
            "storageSupplier": self.__delegate.key
        }

        lun = self._create_item("SanLun", id_props, self.__delegate, "luns")
        if not lun:
            # already logged
            return None

        if self.__topology_update:
            # We want this list rebuilt during each topology collection
            lun.mark_property_for_replacement("poolContributors")

        return SanLun(lun, self.__topology_update, self.__data_update)

    def get_port(self, port_type, ip_or_wwn):
        """

        Create or obtains a SanStoragePort instance. Instances can only be created during
        the inventory phase. During the performance collection phase only previously
        discovered items can be referenced.

        :param port_type: The type of the port. Only "FC" and "ISCSI" are supported
        :type port_type: str
        :param ip_or_wwn: For FC ports, the WWN, for iSCSI ports the IP address. WWNs should be
               all lowercase, with colons removed. The provided WWN will be modified to meet this
               requirement.
        :type ip_or_wwn: str
        :return: :class:`SanStoragePort` | :any:`None`
        """

        port_type = port_type.upper()
        if port_type == "FC":
            container_name = "FC_ports"
            topology_type = "SanStorageSupplierPortFC"
            # ip_or_wwn = ip_or_wwn.lower().translate(dict((ord(char), None) for char in u":"))
            ip_or_wwn = ip_or_wwn.lower().replace(":","")
        elif port_type == "ISCSI":
            container_name = "iSCSi_ports"
            topology_type = "SanStorageSupplierPortISCSI"
        else:
            raise ValueError("Only FC and ISCSI port types are supported")

        container = self.__delegate.get_property(container_name)

        if not container:
            raise ValueError("Missing container " + container_name)

        id_props = {
            "wwn": ip_or_wwn
        }

        # Container should always be available, we a create it when we create this object
        if self.__data_update:
            container = self.__data_update.get_object(container)
        else:
            container = self.__topology_update.get_object(container)

        port = self._create_item(topology_type, id_props, container, "ports")

        if not port:
            # Errors already logged
            return None

        if self.__topology_update:
            port.set_property("name", "Unnamed " + port_type + " Port")
            port.set_property("type", port_type)
            port.set_property("storageSupplier", self.__delegate.key)

        return SanStoragePort(port, self.__topology_update, self.__data_update)

    def get_pool(self, pool_id):
        """
        Create or obtains a SanPool instance. Instances can only be created during
        the inventory phase. During the performance collection phase only previously
        discovered items can be referenced.

        :param pool_id: Globally unique ID for this pool. A human readable name can
           be set with :func:`SanPool.set_property()` if desired
        :type pool_id: str
        :return: :class:`SanPool` | :any:`None`
        """

        id_props = {
            "poolId": pool_id,
            # A pool has a property that points to the storage supplier
            # it is associated with
            "storageSupplier": self.__delegate.key
        }

        pool = self._create_item("SanPool", id_props, self.__delegate, "pools")
        if not pool:
            # already logged
            return None

        if self.__topology_update:
            # We want this list rebuilt during each topology collection
            pool.mark_property_for_replacement("entitiesInPool")
            pool.mark_property_for_replacement("physicalDisks")

        return SanPool(pool, self.__topology_update, self.__data_update)

    def get_controller(self, name):
        """

        Create or obtains a SanController instance. Instances can only be created during
        the inventory phase. During the performance collection phase only previously
        discovered items can be referenced.

        :param name: The name of the controller. Must be unique for this array.
        :type name: str
        :return: :class:`SanController` | :any:`None`
        """

        id_props = {
            "name": name,
            # A controller has a property that points to the storage supplier
            # it is associated with
            "storageSupplier": self.__delegate.key
        }

        controller = self._create_item("SanController", id_props, self.__delegate, "controllers")

        if not controller:
            # Already logged
            return None

        if self.__topology_update:
            # We want this list rebuilt during each topology collection
            iscsi_ports = self.__topology_update.create_object("SanStorageSupplierPorts",
                                                               {
                                                                   "name": "ISCSI",
                                                                   "parent": controller.key
                                                               })
            iscsi_ports.mark_property_for_replacement("ports")
            controller.set_property("iSCSi_ports", iscsi_ports.key)

            fc_ports = self.__topology_update.create_object("SanStorageSupplierPorts",
                                                            {
                                                                "name": "FC",
                                                                "parent": controller.key
                                                            })
            fc_ports.mark_property_for_replacement("ports")
            controller.set_property("FC_ports", fc_ports.key)

        return SanController(controller, self.__topology_update, self.__data_update)


class SanPhysicalDisk(_SanKeyedItem):
    """
    Main class for physical disks (both spinning and flash).

    The instances of this class must be obtained via the
    :func:`SanStorageArray.get_physical_disk()` method. Directly creating this class is not
    supported

    :param delegate: The delegate from the managed topology service we deal with
    :type delegate: :class:`foglight.topology.TopologyObjectUpdate` |
                    :class:`foglight.topology.TopologyObjectData`
    :param topology_update: The topology update in progress or None
    :type topology_update: :class:`foglight.topology.TopologyUpdateTransaction` | None
    :param data_update: The data update in progress or None
    :type data_update: :class:`foglight.topology.TopologyDataCollection` | None
    """

    def __init__(self, delegate, topology_update=None, data_update=None):
        _SanKeyedItem.__init__(self, delegate)
        self.__delegate = delegate
        self.__topology_update = topology_update
        self.__data_update = data_update

    def set_property(self, name, value):
        """
        Sets a property for the disk.

        .. note:: This can only be done during an **inventory/topology** update

        The following properties are supported

        * name - :any:`str` - A human readable name for the disk
        * vendorName - :any:`str` - The disk vendor
        * modelNumber - :any:`str` - The model for the disk
        * rpm - :any:`str` (really) - The RPM rating for the disk. No calculations are done
          with this value
        * size - (:any:`int` | :any:`float` | :any:`long`) - The size of the disk, **in megabytes**
        * diskInterface - :any:`str` - Type of disk. The following values are recommended:
          "SSD", "FC", "SAS", "SATA"
        * role - :any:`str` - role performed by the disk. "parity", "dparity", "spare", etc

        :param name: The name of the property to set
        :type name: str
        :param value: The value for the property
        """
        if name == "size":
            value = Long(value)

        self.__delegate.set_property(name, value)

    def associate_with(self, item):
        """
        Associate this disk with the provided :class:`SanPool` or :class:`SanController`.

        A disk can be associated with zero or more storage pools and with zero or one
        controller.

        The reverse associations (pool to this disk, controller to this disk) will be made
        at the same time.

        .. note:: This can only be done during an **inventory/topology** update

        :param item: The pool or controller this disk is associated with.
        :type item: :class:`SanPool` | :class:`SanController`
        """

        if isinstance(item, SanPool):
            pools = self.__delegate.get_property("pool", ArrayList())
            if not pools.contains(item._key()):
                pools.add(item._key())

            self.__delegate.set_property("pool", pools)

            # build the reverse association as well.
            item._associate_with(self)

        elif isinstance(item, SanController):
            # So we know what controller to roll this disks performance metrics up to.
            self.__delegate.set_property("parentController", item._key())
            self.__delegate.set_property("hasParentController", True)

        else:
            raise ValueError("Physical disks can only be associated with Pools and Controllers")

    def set_state(self, state):
        """
        Sets the state of the disk.

        .. note:: This can only be done during a **performance** update

        :param state: The current state of the disk. Allowed values are

          * "0" - normal
          * "1" - failed (or offline)
          * "2" - removed
          * "3" - new
          * "15" - no information available

        :type state: str
        """
        self.__delegate.set_observation_value("state", state)

    def set_metric(self, name, value):
        """
        Sets the named metric to the provided value.

        .. note:: This can only be done during a **performance** update

        The following metrics are supported. And must be provided in the listed units and
        represent an average during the sample period. A :class:`foglight.topology.MetricSummary`
        can be used to provide more details statistical values than just a simple average.

        * opsRead - per second - number of read operations
        * opsWrite - per second - number of write operations
        * opsTotal - per second - number of total operations
        * bytesRead - byte/second - number of bytes read
        * bytesWrite - byte/second - number of bytes writen
        * bytesTotal - byte/second - number of bytes total
        * latencyRead - millisecond - read latency (per op)
        * latencyWrite - millisecond - write latency (per op)
        * latencyTotal - millisecond - total latency (per op)
        * busy - percent - percent busy
        * avgQueueDepth - count - queue depth

        For most metrics, if a total value is not provided, it will be computed using the
        sum of the read and write (and other if available) values.

        :param name: Name of the metric to be set
        :type name: str
        :param value: value for the metric
        :type value: :any:`int` | :any:`long` | :any:`float` | :class:`foglight.topology.MetricSummary`
        """

        if isinstance(value, (int, long, float)):
            self.__delegate.set_metric_value(name, value)
        else:
            self.__delegate.set_observation_value(name, value)


class SanLun(_SanTopologyItem):
    """
    Main class for LUNs.

    The instances of this class must be obtained via the
    :func:`SanStorageArray.get_lun()` method. Directly creating this class is not
    supported

    :param delegate: The delegate from the managed topology service we deal with
    :type delegate: :class:`foglight.topology.TopologyObjectUpdate` |
                    :class:`foglight.topology.TopologyObjectData`
    :param topology_update: The topology update in progress or None
    :type topology_update: :class:`foglight.topology.TopologyUpdateTransaction` | None
    :param data_update: The data update in progress or None
    :type data_update: :class:`foglight.topology.TopologyDataCollection` | None
    """

    def __init__(self, delegate, topology_update=None, data_update=None):
        _SanTopologyItem.__init__(self, delegate)
        self.__delegate = delegate
        self.__topology_update = topology_update
        self.__data_update = data_update

    def set_property(self, name, value):
        """
        Sets a property for the LUN.

        .. note:: This can only be done during an **inventory/topology** update

        The following properties are supported

        * name - :any:`str` - A human readable name for the disk
        * size - (:any:`int` | :any:`float` | :any:`long`) - The size of the LUN, **in megabytes**
        * advertisedSize - (:any:`int` | :any:`float` | :any:`long`) - The advertised size
          of the LUN, **in megabytes**
        * protection - :any:`str` - The RAID level or setting for this LUN
        * isThinProvisioned - :any:`bool` - Whether or not the LUN is thin provisioned.

        :param name: The name of the property to set
        :type name: str
        :param value: The value for the property
        """
        if name in ["size", "advertisedSize"]:
            value = Long(value)

        self.__delegate.set_property(name, value)

    def associate_with(self, pool):
        """
        Associate this LUN with the provided :class:`SanPool`. A LUN can be associated
        with zero or more storage pools.

        .. note:: This can only be done during an **inventory/topology** update

        The association indicates that the LUN gets some or all of it's storage from the pool.
        The exact amount of the storage contributed it considered a performance observation
        and can only be set during the performance collection cycle.

        :param pool: The pool this disk is associated with.
        :type pool: :class:`SanPool`
        """

        id_props = {
            "lun": self.__delegate.key,
            "contributor": pool._key()
        }

        contrib = self.__topology_update.create_object("SanLunPoolContributor", id_props)

        # Need at least one property set on the object or it will not be submitted
        contrib.set_property("name", "Unnamed SanLunPoolContributor")

        contributors = self.__delegate.get_property("poolContributors", ArrayList())

        if not contributors.contains(contrib.key):
            contributors.add(contrib.key)

        self.__delegate.set_property("poolContributors", contributors)

        # build the reverse association as well.
        pool._associate_with(self)

    def set_state(self, state):
        """
        Sets the state of the LUN.

        .. note:: This can only be done during a **performance** update

        :param state: The current state of the LUN. Allowed values are

          * "0" - normal
          * "1" - failed
          * "2" - removed (or offline)
          * "4" - degraded
          * "5" - rebuilding
          * "15" - no information available

        :type state: str
        """
        self.__delegate.set_observation_value("state", state)

    def set_metric(self, name, value):
        """
        Sets the named metric to the provided value.

        .. note:: This can only be done during a **performance** update

        The following metrics are supported. And must be provided in the listed units and
        represent an average during the sample period. A :class:`foglight.topology.MetricSummary`
        can be used to provide more details statistical values than just a simple average.

        * opsRead - per second - number of read operations per second during the sample period
        * opsWrite - per second - number of write operations per second during the sample period
        * opsOther - per second - number of other operations per second during the sample period
        * opsTotal - per second - number of total operations per second during the sample period
        * bytesRead - byte/second - number of bytes read per second during the sample period
        * bytesWrite - byte/second - number of bytes writen per second during the sample period
        * bytesTotal - byte/second - number of bytes total per second during the sample period
        * latencyRead - millisecond - average read latency (per op)
        * latencyWrite - millisecond - average write latency (per op)
        * latencyOther - millisecond - average other latency (per op)
        * latencyTotal - millisecond - average total latency (per op)
        * busy - percent - average percent busy during the sample period
        * avgQueueDepth - count - average queue depth during the sample period
        * cacheHits - percent - percentage of LUN operations that are satisfied by the cache

        For most metrics, if a total value is not provided, it will be computed using the
        sum of the read and write (and other if available) values.

        :param name: name of the metric to be set
        :type name: str
        :param value: value for the metric
        :type value: :any:`int` | :any:`long` | :any:`float` | :class:`foglight.topology.MetricSummary`
        """

        if isinstance(value, (int, long, float)):
            self.__delegate.set_metric_value(name, value)
        else:
            self.__delegate.set_observation_value(name, value)


class SanPool(_SanTopologyItem):
    """
    Main class for Pools (or volumes or aggregates).

    The instances of this class must be obtained via the
    :func:`SanStorageArray.get_pool()` method. Directly creating this class is not
    supported

    :param delegate: The delegate from the managed topology service we deal with
    :type delegate: :class:`foglight.topology.TopologyObjectUpdate` |
                    :class:`foglight.topology.TopologyObjectData`
    :param topology_update: The topology update in progress or None
    :type topology_update: :class:`foglight.topology.TopologyUpdateTransaction` | None
    :param data_update: The data update in progress or None
    :type data_update: :class:`foglight.topology.TopologyDataCollection` | None
    """

    def __init__(self, delegate, topology_update=None, data_update=None):
        _SanTopologyItem.__init__(self, delegate)
        self.__delegate = delegate
        self.__topology_update = topology_update
        self.__data_update = data_update

    def set_property(self, name, value):
        """
        Sets a property for the pool.

        .. note:: This can only be done during an **inventory/topology** update

        The following properties are supported

        * name - :any:`str` - A human readable name for the pool

        Most properties for a pool are derived from the physical disks and LUNs associated
        with the pool.

        :param name: The name of the property to set
        :type name: str
        :param value: The value for the property
        """
        if name in ["size", "advertisedSize"]:
            value = Long(value)

        self.__delegate.set_property(name, value)

    def set_metric(self, name, value):
        """
        Sets the named metric to the provided value.

        .. note:: This can only be done during a **performance** update

        The following metrics are supported. And must be provided in the listed units and
        represent an average during the sample period. A :class:`foglight.topology.MetricSummary`
        can be used to provide more details statistical values than just a simple average.

        * conf_capacity - megabytes - configured capacity of the pool
        * conf_used - megabytes - how much of the configured capacity has been consumed
          (given out to associated LUNs)
        * conf_committed - megabytes - how much of the configured capacity has been committed
          (if this is different from the `conf_used` value, will be computed from `conf_capacity`
          and `conf_available` )
        * conf_available - megabytes - how much of the configured capacity is still available
        * conf_LunSize - megabytes - the size of this pool as advertised to associated LUNs.
          This can be larger that `conf_capacity` for thin provisioned pools

        :param name: name of the metric to set
        :type name: str
        :param value: value for the metric
        :type value: :any:`int` | :any:`long` | :any:`float` | :class:`foglight.topology.MetricSummary`
        """

        if isinstance(value, (int, long, float)):
            self.__delegate.set_metric_value(name, value)
        else:
            self.__delegate.set_observation_value(name, value)

    def _associate_with(self, item):
        """
        Associate this Pool with the provided :class:`SanPhysicalDisk` or :class:`SanLun`

        .. note:: This can only be done during an **inventory/topology** update

        :param item: The disk to associate with
        :type item: :class:`SanPhysicalDisk`|:class:`SanLun`
        """

        if isinstance(item, SanPhysicalDisk):
            disks = self.__delegate.get_property("physicalDisks", ArrayList())
            if not disks.contains(item._key()):
                disks.add(item._key())
                self.__delegate.set_property("physicalDisks", disks)
        else:
            luns = self.__delegate.get_property("entitiesInPool", ArrayList())
            if not luns.contains(item._key()):
                luns.add(item._key())
                self.__delegate.set_property("entitiesInPool", luns)


class SanController(_SanKeyedItem):
    """
    Main class for controllers (or members, nodes, etc).

    The instances of this class must be obtained via the
    :func:`SanStorageArray.get_controller()` method. Directly creating this class is not
    supported

    :param delegate: The delegate from the managed topology service we deal with
    :type delegate: :class:`foglight.topology.TopologyObjectUpdate` |
                    :class:`foglight.topology.TopologyObjectData`
    :param topology_update: The topology update in progress or None
    :type topology_update: :class:`foglight.topology.TopologyUpdateTransaction` | None
    :param data_update: The data update in progress or None
    :type data_update: :class:`foglight.topology.TopologyDataCollection` | None
    """

    def __init__(self, delegate, topology_update=None, data_update=None):
        _SanKeyedItem.__init__(self, delegate)
        self.__delegate = delegate
        self.__topology_update = topology_update
        self.__data_update = data_update

    def set_property(self, name, value):
        """
        Sets a property for the controller.

        .. note:: This can only be done during an **inventory/topology** update

        The following properties are supported

        * ip - :any:`str` - IP address (free form, this field is for display only)
        * networkName - :any:`str` - DNS name of the controller
        * softwareVersion - :any:`str` - version for the controller's firmware or OS

        :param name: The name of the property to set
        :type name: str
        :param value: The value for the property
        """

        self.__delegate.set_property(name, value)

    def set_metric(self, name, value):
        """
        Sets the named metric to the provided value.

        .. note:: This can only be done during a **performance** update

        The following metrics are supported. And must be provided in the listed units and
        represent an average during the sample period. A :class:`foglight.topology.MetricSummary`
        can be used to provide more details statistical values than just a simple average.

        * busy - percent - Average percent utilization for the controller during the sample period
        * errors - percent - percentage of operations that failed
        * latencyTotalBlock - millisecond/operation - average latency per block operation
        * latencyTotalFile - millisecond/operation - average latency per file operation

        * bytesTotalFile - byte/second - average number of processed bytes per second during the sample period
        * bytesWriteFile - byte/second - average number of bytes written per second during the sample period
        * bytesReadFile - byte/second - average number of bytes read per second during the sample period
        * bytesTotalBlock - byte/second - average number of processed bytes per second during the sample period
        * bytesWriteBlock - byte/second - average number of bytes written per second during the sample period
        * bytesReadBlock - byte/second - average number of bytes read per second during the sample period

        * opsTotalFile - per second - average number of operations per second during the sample period
        * opsWriteFile - per second - average number of read operations per second during the sample period
        * opsReadFile - per second - average number of write operations per second during the sample period
        * opsTotalBlock - per second - average number of operations per second during the sample period
        * opsWriteBlock - per second - average number of read operations per second during the sample period
        * opsReadBlock - per second - average number of write operations per second during the sample period

        For most metrics, if a total value is not provided, it will be computed using the
        sum of the read and write (and other if available) values.

        :param name: name of the metric to be set
        :type name: str
        :param value: value for the metric
        :type value: :any:`int` | :any:`long` | :any:`float` | :class:`foglight.topology.MetricSummary`
        """

        if isinstance(value, (int, long, float)):
            self.__delegate.set_metric_value(name, value)
        else:
            self.__delegate.set_observation_value(name, value)

    def set_state(self, state):
        """
        Sets the state of the controller.

        .. note:: This can only be done during a **performance** update

        :param state: The current state of the controller. Allowed values are

          * "0" - normal
          * "1" - failed
          * "2" - removed (or offline)
          * "4" - degraded
          * "15" - no information available

        :type state: str
        """
        self.__delegate.set_observation_value("state", state)

    def _associate_with(self, port, port_type):
        """
        Associates the port with the correct container in this controller.
        """

        if port_type == "FC":
            controller_property = "FC_ports"
        elif port_type == "ISCSI":
            controller_property = "iSCSi_ports"
        else:
            raise ValueError("Unrecognized port type: " + port_type)

        # Convert to jsut the key, we don't need the real port
        port = port._key()

        # get the container from the controller
        container = self.__delegate.get_property(controller_property)
        if container:
            try:
                container = self.__topology_update.get_object(container)
            except:
                _logger.error("Could not load port container object {0}".format(port_type))
                return

        ports = container.get_property("ports", ArrayList())
        if not ports.contains(port):
            ports.add(port)

        container.set_property("ports", ports)


class SanStoragePort(object):
    """
    Main class for both FC and iSCSI ports on storage arrays.

    The instances of this class must be obtained via the
    :func:`SanStorageArray.get_controller()` method. Directly creating this class is not
    supported

    :param delegate: The delegate from the managed topology service we deal with
    :type delegate: :class:`foglight.topology.TopologyObjectUpdate` |
                    :class:`foglight.topology.TopologyObjectData`
    :param topology_update: The topology update in progress or None
    :type topology_update: :class:`foglight.topology.TopologyUpdateTransaction` | None
    :param data_update: The data update in progress or None
    :type data_update: :class:`foglight.topology.TopologyDataCollection` | None
    """

    def __init__(self, delegate, topology_update=None, data_update=None):
        self.__delegate = delegate
        self.__topology_update = topology_update
        self.__data_update = data_update

    def set_state(self, state):
        """
        Sets the state of the port.

        .. note:: This can only be done during a **performance** update

        :param state: The current state of the port. Allowed values are

          * "0" - normal
          * "1" - failed (or offline)
          * "8" - suspended
          * "15" - no information available

        :type state: str
        """
        self.__delegate.set_observation_value("state", state)

    def _key(self):
        return self.__delegate.key

    def set_property(self, name, value):
        """
        Sets a property for the port.

        .. note:: This can only be done during an **inventory/topology** update

        The following properties are supported

        * name - :any:`str` - A human readable name for the port. Generally the IQN for iSCSI ports
          or the WWN (lowercase, no colons. use `value.lower().translate(None, ':')`) for FC ports
        * alias - :any:`str` - Port alias
        * ipV4 - :any:`str` - IPv4 address for iSCSI ports (optional)
        * ipV6 - :any:`str` - IPv6 address for iSCSI ports (optional)

        :param name: The name of the property to set
        :type name: str
        :param value: The value for the property
        """

        self.__delegate.set_property(name, value)

    def set_metric(self, name, value):
        """
        Sets the named metric to the provided value.

        .. note:: This can only be done during a **performance** update

        The following metrics are supported. And must be provided in the listed units and
        represent an average during the sample period. A :class:`foglight.topology.MetricSummary`
        can be used to provide more details statistical values than just a simple average.

        * currentSpeedMb - megabits/second - current port speed in Mb/s
        * maxSpeedMb - megabits/second - maximum port speed in Mb/s
        * bytesTotal - per second - average number of processed bytes per second during the sample period
        * bytesWrite - per second - average number of bytes written per second during the sample period
        * bytesRead - per second - average number of bytes read per second during the sample period
        * opsTotal - per second - average number of operations per second during the sample period
        * opsWrite - per second - average number of read operations per second during the sample period
        * opsRead - per second - average number of write operations per second during the sample period

        For most metrics, if a total value is not provided, it will be computed using the
        sum of the read and write (and other if available) values.

        :param name: name of the metric to be set
        :type name: str
        :param value: value for the metric
        :type value: :any:`int` | :any:`long` | :any:`float` | :class:`foglight.topology.MetricSummary`
        """

        if isinstance(value, (int, long, float)):
            self.__delegate.set_metric_value(name, value)
        else:
            self.__delegate.set_observation_value(name, value)

    def associate_with(self, item):
        """
        Associate this port with the provided :class:`SanController`

        .. note:: This can only be done during an **inventory/topology** update

        A port should only be associated with one controller at a time.

        :param item: The controller to associate with
        :type item: :class:`SanController`
        """

        self.__delegate.set_property("controller", item._key())

        # Now make the reverse association, this is a bit more painful (for the controller anyway)
        item._associate_with(self, self.__delegate.get_property("type"))
