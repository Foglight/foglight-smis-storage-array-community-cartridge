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
Post processing roll ups for both inventory and topology collections.

You should not need to call any of these methods directly, they are called automatically
as part of the data submission process.
"""

import os
import shelve

import foglight.logging
import foglight.utils
import foglight.topology

from java.util import ArrayList

_logger = foglight.logging.get_logger("fsm-rollups")


def _load_provider_properties(array_name):
    # Default everything to true until we have known good value.
    props = {
        "hasAvgQueueDepth": True,
        "hasControllerBusy": True,
        "hasControllerBytes": True,
        "hasControllerBytesBlock": True,
        "hasControllerBytesFile": True,
        "hasControllerErrors": True,
        "hasControllerLatencyBlock": True,
        "hasControllerLatencyFile": True,
        "hasControllerOps": True,
        "hasControllerOpsBlock": True,
        "hasControllerOpsFile": True,
        "hasDiskBusy": True,
        "hasDiskBytes": True,
        "hasDiskErrorsHard": True,
        "hasDiskErrorsSoft": True,
        "hasDiskLatency": True,
        "hasDiskOps": True,
        "hasDiskQueueDepth": True,
        "hasInitiatorPorts": True,
        "hasLunBusy": True,
        "hasLunBytes": True,
        "hasLunCacheHits": True,
        "hasLunLatency": True,
        "hasLunLatencyOther": True,
        "hasLunLatencyRW": True,
        "hasLunOps": True,
        "hasLunOpsOther": True,
        "hasLunQueueDepth": True,
        "hasLunRebuilding": True,
        "hasMemberDiskLatency": False,
        "hasMemberLatency": False,
        "hasPoolBytesToDisk": True,
        "hasPoolCfgCapacity": True,
        "hasPoolDiskLatency": True,
        "hasPoolLatency": True,
        "hasPoolOpsToDisk": True,
        "hasPoolRawCapacity": False,
        "hasPoolRebuilding": True,
        "hasPortBytes": True,
        "hasPortBytesRead": True,
        "hasPortBytesWrite": True,
        "hasPortOps": True,
        "hasPortUtilization": True,
        "hasPortUtilizationMax": True,
        "hasRawLunSize": False,
        "hasVolBytes": False,
        "hasVolLatency": False,
        "hasVolOps": False,
    }

    # Try and load from the cache
    location = foglight.get_version_specific_directory()
    filename = os.path.join(location, "collection-tracker")

    _logger.debug("Checking for provider properties in {0}.dat".format(filename))
    if os.path.exists(filename + ".dat"):
        state_store = shelve.open(filename)
        key = str('provider_properties_' + array_name.toString())
        saved_props = state_store.get(key)
        state_store.close()
        if saved_props:
            props = saved_props

    return props


def _save_provider_properties(array_name, props):
    location = foglight.get_version_specific_directory()
    filename = os.path.join(location, "collection-tracker")
    state_store = shelve.open(filename)
    key = str('provider_properties_' + array_name.toString())
    state_store[key] = props
    state_store.sync()
    state_store.close()


def _accumulate_metric(existing, addition):
    if existing is None and addition is None:
        return None

    if isinstance(existing, (foglight.topology.MetricSummary_Java, foglight.topology.MetricSummary)):
        l_value = existing.sum
        l_min = existing.min
        l_max = existing.max
    elif isinstance(existing, (int, long, float)):
        l_value = existing
        l_min = existing
        l_max = existing
    else:
        l_value = 0
        l_min = 0
        l_max = 0

    if isinstance(addition, (foglight.topology.MetricSummary_Java, foglight.topology.MetricSummary)):
        l_value += addition.sum
        l_min += addition.min
        l_max += addition.max
    elif isinstance(addition, (int, long, float)):
        l_value += addition
        l_min += addition
        l_max += addition

    return foglight.topology.MetricSummary(1, l_value, l_value*l_value, l_min, l_max)


def _synthesize_metrics(obj, dest_name, sources):
    existing = obj.get_observation_value(dest_name)

    if existing is not None:
        # already have a value there
        return

    # No value, have to create one in if possible
    value = None
    for source in sources:
        # Don't try to fill in a value if a sources does not exist. _accumulate
        # a missing source by assuming zero values, and here we want no value.`
        obs = obj.get_observation_value(source)
        if obs is not None:
            value = _accumulate_metric(value, obs)

    if value is not None:
        obj.set_observation_value(dest_name, value)


def _accumulate_state(obj, states, fail_values):
    states["total"] += 1
    value = obj.get_observation_value("state")
    if value in fail_values:
        states["busted"] += 1


def _check_for_property(props, prop_name, obj, required_values):
    for value_name in required_values:
        val = obj.get_observation_value(value_name)
        if val is None:
            return

    props[prop_name] = True


def topology_post_processor(update, model):
    """
    Does the topology post processing on the provided model.

    .. warning:: This method is not intended to be called directly.

    :param update:
    :param model:
    """
    _logger.debug("Starting inventory post-processing")

    # All we need to do here is collect some summary information about what was discovered and
    # log it.

    num_arrays = 0
    num_disks = 0
    num_luns = 0
    num_pools = 0
    num_controllers = 0
    num_fc_ports = 0
    num_iscsi_ports = 0

    key = foglight.topology.make_object_key("SanStorageArrays",
                                            {"name": "SanStorageArrays"})
    arrays = update.get_object(key)
    if arrays:
        arrays = arrays.get_property("storageArrays", [])
    else:
        arrays = []

    for array in arrays:
        num_arrays += 1

        # convert from key to object
        array = update.get_object(array)

        num_pools += array.get_property("pools", ArrayList()).size()
        num_disks += array.get_property("physicalDisks", ArrayList()).size()
        num_luns += array.get_property("luns", ArrayList()).size()
        num_controllers += array.get_property("controllers", ArrayList()).size()

        # urg.
        ports = array.get_property("FC_ports")
        if ports:
            try:
                ports = update.get_object(ports)
            except:
                pass
        if ports:
            num_fc_ports += ports.get_property("ports", ArrayList()).size()

        ports = array.get_property("iSCSi_ports")
        if ports:
            try:
                ports = update.get_object(ports)
            except:
                pass
        if ports:
            num_iscsi_ports += ports.get_property("ports", ArrayList()).size()

        #
        # These are cached from the last performance collection
        # This is the old method of submitting the "has*" values, and is
        # deprecated in FSM 4.4 and later. We're using both methods for now
        # so that older Python-based storage agents remain forward compatible.
        #
        props = _load_provider_properties(array.key)
        for k, v in props.iteritems():
            array.set_property(k, v)

        # A pool has think entities if any LUN in it is thin provisioned
        for pool in array.get_property("pools", []):
            try:
                pool = update.get_object(pool)
            except:
                continue

            thin = False
            # A pool is thin provisioned if any LUN in it is thin provisioned
            luns = pool.get_property("entitiesInPool", [])
            for lun in luns:
                try:
                    lun = update.get_object(lun)
                except:
                    continue

                if lun.get_property("isThinProvisioned", False):
                    thin = True
                    break

            pool.set_property("hasThinEntities", thin)

    _logger.verbose("Inventory collection discovered:\n"
                    "  {0} storage arrays\n"
                    "  {1} controllers\n"
                    "  {2} FC ports\n"
                    "  {3} iSCSI ports\n"
                    "  {4} pools\n"
                    "  {5} LUNs\n"
                    "  {6} physical disks".format(num_arrays,
                                                  num_controllers,
                                                  num_fc_ports,
                                                  num_iscsi_ports,
                                                  num_pools,
                                                  num_luns,
                                                  num_disks))


def _disk_roll_up(array, props, update, frequency):
    states = {"total": 0.0, "busted": 0.0}
    fail_values = ["1", "2"]
    disk_capacity = 0

    disks = array.get_property("physicalDisks", [])
    for disk in disks:
        try:
            disk = update.get_object(disk)
        except:
            continue

        disk.set_frequency(frequency)

        disk_state = disk.get_observation_value("state") or "0"
        _accumulate_state(disk, states, fail_values)

        _synthesize_metrics(disk, "opsTotal", ["opsRead", "opsWrite"])
        _synthesize_metrics(disk, "bytesTotal", ["bytesRead", "bytesWrite"])
        _synthesize_metrics(disk, "latencyTotal", ["latencyRead", "latencyWrite"])

        _check_for_property(props, "hasDiskOps", disk, ["opsRead", "opsWrite"])
        _check_for_property(props, "hasDiskOps", disk, ["opsTotal"])
        _check_for_property(props, "hasDiskBytes", disk, ["bytesRead", "bytesWrite", "bytesTotal"])
        _check_for_property(props, "hasDiskBusy", disk, ["busy"])
        _check_for_property(props, "hasDiskQueueDepth", disk, ["avgQueueDepth"])
        _check_for_property(props, "hasDiskLatency", disk, ["latencyRead", "latencyWrite", "latencyTotal"])

        disk_size = disk.get_property("size", 0)
        disk_capacity += disk_size

        # Roll up metrics to all pools this disk is associated with
        pools = disk.get_property("pool", [])
        for pool in pools:
            pool = update.get_object(pool)

            # Disk capacity is passed on to all pools the disk is associated with
            # todo: not sure about this. Is it reasonable to assign the size to multiple pools?
            cap = _accumulate_metric(pool.get_observation_value("raw_capacity"), disk_size)
            pool.set_observation_value("raw_capacity", cap)

            # Metrics, if they are available, are passed along to the pool as well.
            for metric in ["opsRead", "opsWrite", "opsTotal",
                           "bytesRead", "bytesWrite", "bytesTotal",
                           "latencyTotal"]:
                val = disk.get_observation_value(metric)
                if val is not None:
                    val = _accumulate_metric(val, pool.get_observation_value(metric + "Disk"))
                    pool.set_observation_value(metric + "Disk", val)

            # The physical state of a pool is the worst of the physical states of all the
            # disks in the pool.
            pool_state = pool.get_observation_value("state") or "0"
            if int(disk_state) >= int(pool_state):
                pool.set_observation_value("state", disk_state)

    # Total disk size rolls up to the array that owns the disk
    array.set_metric_value("disk_capacity", disk_capacity)

    array.set_metric_value("disks_FailedOrOffline", states["busted"])
    if states["total"] > 0:
        array.set_metric_value("disks_FailedOrOffline_pct",
                               (states["busted"] / states["total"] * 100.0))


def _lun_roll_up(array, props, update, frequency):
    luns = array.get_property("luns", [])

    degraded = {"total": 0.0, "busted": 0.0}
    failed = {"total": 0.0, "busted": 0.0}
    rebuilding = {"total": 0.0, "busted": 0.0}

    lun_advertised = 0
    lun_usable = 0
    for lun in luns:
        try:
            lun = update.get_object(lun)
        except:
            continue

        lun.set_frequency(frequency)

        _accumulate_state(lun, failed, ["1", "2"])
        _accumulate_state(lun, degraded, ["4"])
        _accumulate_state(lun, rebuilding, ["5"])

        _synthesize_metrics(lun, "opsTotal", ["opsRead", "opsWrite", "opsOther"])
        _synthesize_metrics(lun, "bytesTotal", ["bytesRead", "bytesWrite"])
        _synthesize_metrics(lun, "latencyTotal", ["latencyRead", "latencyWrite", "latencyOther"])

        _check_for_property(props, "hasLunOps", lun, ["opsRead", "opsWrite", "opsTotal"])
        _check_for_property(props, "hasLunOpsOther", lun, ["opsOther"])
        _check_for_property(props, "hasLunBytes", lun, ["bytesRead", "bytesWrite", "bytesTotal"])
        _check_for_property(props, "hasLunLatency", lun, ["latencyTotal"])
        _check_for_property(props, "hasLunLatencyRW", lun, ["latencyRead", "latencyWrite"])
        _check_for_property(props, "hasLunLatencyOther", lun, ["latencyOther"])
        _check_for_property(props, "hasLunQueueDepth", lun, ["avgQueueDepth"])
        _check_for_property(props, "hasLunBusy", lun, ["busy"])
        _check_for_property(props, "hasLunCacheHits", lun, ["cacheHits"])

        lun_usable += lun.get_property("size", 0)
        lun_advertised += lun.get_property("advertisedSize", 0)

    # LUN sizes roll all the way up to the array
    array.set_metric_value("lun_usable_capacity", lun_usable)
    array.set_metric_value("conf_LunSize", lun_advertised)

    array.set_metric_value("luns_FailedOrOffline", failed["busted"])
    if failed["total"] > 0:
        array.set_metric_value("luns_FailedOrOffline_pct",
                               (failed["busted"] / failed["total"] * 100.0))

    array.set_metric_value("luns_Degraded", degraded["busted"])
    if degraded["total"] > 0:
        array.set_metric_value("luns_Degraded_pct",
                               (degraded["busted"] / degraded["total"] * 100.0))

    array.set_metric_value("luns_Rebuilding", rebuilding["busted"])
    if rebuilding["total"] > 0:
        array.set_metric_value("luns_Rebuilding_pct",
                               (rebuilding["busted"] / rebuilding["total"] * 100.0))


def _pool_roll_up(array, props, update, frequency):

    disk_used = None
    pools = array.get_property("pools", [])
    for pool in pools:
        try:
            pool = update.get_object(pool)
        except:
            continue

        pool.set_frequency(frequency)

        _check_for_property(props, "hasAvgQueueDepth", pool, ["avgQueueDepth"])
        _check_for_property(props, "hasPoolDiskLatency", pool, ["latencyTotalDisk"])
        _check_for_property(props, "hasPoolBytesToDisk", pool, ["bytesTotalDisk"])
        _check_for_property(props, "hasPoolOpsToDisk", pool, ["opsTotalDisk"])
        _check_for_property(props, "hasPoolDiskLatency", pool, ["latencyTotalDisk"])
        _check_for_property(props, "hasPoolRawCapacity", pool, ["raw_capacity"])
        _check_for_property(props, "hasPoolCfgCapacity", pool, ["conf_capacity"])

        pool_size = pool.get_observation_value("raw_capacity")
        if pool_size is not None:
            disk_used = _accumulate_metric(disk_used, pool_size)

        total = pool.get_observation_value("conf_capacity")
        used = pool.get_observation_value("conf_used")
        free = pool.get_observation_value("conf_available")
        advertised = pool.get_observation_value("conf_LunSize")
        committed = pool.get_observation_value("conf_committed")
        pct_avail = pool.get_observation_value("conf_pct_available")

        if free is None:
            if total is not None and used is not None:
                f = total.sum - used.sum
                free = foglight.topology.MetricSummary(1, f, f*f, f, f)
                pool.set_observation_value("conf_available", free)

        if used is None:
            if total is not None and free is not None:
                f = total.sum - free.sum
                used = foglight.topology.MetricSummary(1, f, f*f, f, f)
                pool.set_observation_value("conf_used", used)

        if committed is None:
            # no explicit value, use total -  free
            if total is not None and free is not None:
                pool.set_metric_value("conf_committed", max(0, total.sum - free.sum))

        if pct_avail is None:
            if total is not None and free is not None:
                f = 100.0 * (free.sum / total.sum)
                pool.set_metric_value("conf_pct_available", f)

        # Check for over commitment on this pool.
        # This is defined as:
        #    overcommitted = advertised_to_luns - (used+free)
        if all(v is not None for v in [advertised, used, free]):
            overcommitted = advertised.sum - (used.sum + free.sum)
            if overcommitted > 0:
                pool.set_metric_value("conf_LunOvercommitted", overcommitted)
        else:
            pool.set_metric_value("conf_LunOvercommitted", 0)

    # We'll want to subtract the sizes of these pool from the total amount of free
    # disk space we found when processing disks.
    #
    #  disk_free = sum(disk_capacity) - sum(pool_capacity)

    disk_capacity = array.get_observation_value("disk_capacity")

    if disk_capacity is not None and disk_used is not None:
        # This can be negative if a disk is assigned to multiple pools. That
        # theoretically means that there is more raw storage advertised than is
        # currently available on the array
        array.set_metric_value("disk_free", max(0, disk_capacity.sum - disk_used.sum))


def _controller_roll_up(array, props, update, frequency):

    failed = {"total": 0.0, "busted": 0.0}

    controllers = array.get_property("controllers", [])
    for controller in controllers:
        try:
            controller = update.get_object(controller)

            _accumulate_state(controller, failed, ["1", "2", "4"])

        except:
            continue

        _accumulate_state(controller, failed, ["1", "2", "4"])

        _synthesize_metrics(controller, "bytesTotalFile", ["bytesReadFile", "bytesWriteFile"])
        _synthesize_metrics(controller, "bytesTotalBlock", ["bytesReadBlock", "bytesWriteBlock"])
        _synthesize_metrics(controller, "opsTotalFile", ["opsReadFile", "opsWriteFile"])
        _synthesize_metrics(controller, "opsTotalBlock", ["opsReadBlock", "opsWriteBlock"])

        # Rolled up / combined data VFGLS-517
        _synthesize_metrics(controller, "bytesRead", ["bytesReadFile", "bytesReadBlock"])
        _synthesize_metrics(controller, "bytesWrite", ["bytesWriteFile", "bytesWriteBlock"])
        _synthesize_metrics(controller, "bytesTotal", ["bytesTotalFile", "bytesTotalBlock"])
        _synthesize_metrics(controller, "opsRead", ["opsReadFile", "opsReadBlock"])
        _synthesize_metrics(controller, "opsWrite", ["opsWriteFile", "opsWriteBlock"])
        _synthesize_metrics(controller, "opsTotal", ["opsTotalFile", "opsTotalBlock"])

        _check_for_property(props, "hasControllerBusy", controller, ["busy"])
        _check_for_property(props, "hasControllerErrors", controller, ["errors"])
        _check_for_property(props, "hasControllerLatencyBlock", controller, ["latencyTotalBlock"])
        _check_for_property(props, "hasControllerLatencyFile", controller, ["latencyTotalFile"])
        _check_for_property(props, "hasControllerBytes", controller, ["bytesRead", "bytesWrite"])
        _check_for_property(props, "hasControllerBytes", controller, ["bytesTotal"])
        _check_for_property(props, "hasControllerBytesFile", controller, ["bytesReadFile", "bytesWriteFile"])
        _check_for_property(props, "hasControllerBytesFile", controller, ["bytesTotalFile"])
        _check_for_property(props, "hasControllerBytesBlock", controller, ["bytesReadBlock", "bytesWriteBlock"])
        _check_for_property(props, "hasControllerBytesBlock", controller, ["bytesTotalBlock"])
        _check_for_property(props, "hasControllerOpsFile", controller, ["opsReadFile", "opsWriteFile"])
        _check_for_property(props, "hasControllerOpsFile", controller, ["opsTotalFile"])
        _check_for_property(props, "hasControllerOpsBlock", controller, ["opsReadBlock", "opsWriteBlock"])
        _check_for_property(props, "hasControllerOpsBlock", controller, ["opsTotalBlock"])

        if props["hasControllerOpsFile"] or props["hasControllerOpsBlock"]:
            props["hasControllerOps"] = True
        if props["hasControllerBytesFile"] or props["hasControllerBytesBlock"]:
            props["hasControllerBytes"] = True

        controller.set_frequency(frequency)

    array.set_metric_value("controllers_FailedOrOffline", failed["busted"])
    if failed["total"] > 0:
        array.set_metric_value("controllers_FailedOrOffline_pct",
                               (failed["busted"] / failed["total"] * 100.0))


def _port_roll_up_to_container(port, container):
    speed = _accumulate_metric(port.get_observation_value("currentSpeedMb"),
                               container.get_observation_value("totalLinkSpeed"))
    container.set_observation_value("totalLinkSpeed", speed)

    # currentSpeedInMegaBits = speed.sum

    for metric in ["bytesRead", "bytesWrite", "bytesTotal",
                   "opsRead", "opsWrite", "opsTotal"]:
        s = _accumulate_metric(port.get_observation_value(metric),
                               container.get_observation_value(metric))
        container.set_observation_value(metric, s)


def _port_roll_up(array, props, update, frequency):

    holders = {
        "FC_ports": "fcPorts_FailedOrOffline",
        "iSCSi_ports": "ipPorts_FailedOrOffline"
    }

    for key in holders:
        holder = array.get_property(key)
        try:
            holder = update.get_object(holder)
        except:
            continue

        failed = {"total": 0.0, "busted": 0.0}

        ports = holder.get_property("ports", [])
        for port in ports:
            try:
                port = update.get_object(port)
            except:
                continue

            port.set_frequency(frequency)

            _accumulate_state(port, failed, ["1", "8"])

            # Compute totals when needed
            _synthesize_metrics(port, "opsTotal", ["opsRead", "opsWrite"])
            _synthesize_metrics(port, "bytesTotal", ["bytesRead", "bytesWrite"])

            #
            # Compute utilization values
            #

            current_speed = port.get_observation_value("currentSpeedMb")
            if current_speed:
                # Convert from metric summary megabits/second to double bytes/second
                current_speed = current_speed.sum * (1000000.0 / 8.0)

            max_speed = port.get_observation_value("maxSpeedMb")
            if max_speed:
                # Convert from metric summary megabits/second to double bytes/second
                max_speed = max_speed.sum * (1000000.0 / 8.0)

            bytes_read = port.get_observation_value("bytesRead")
            if bytes_read:
                bytes_read = bytes_read.sum

            bytes_write = port.get_observation_value("bytesWrite")
            if bytes_write:
                bytes_write = bytes_write.sum

            if bytes_read and current_speed and current_speed > 0:
                util = bytes_read / current_speed * 100.0
                port.set_metric_value("bytesReadUtilization", util)
            if bytes_write and current_speed and current_speed > 0:
                util = bytes_write / current_speed * 100.0
                port.set_metric_value("bytesWriteUtilization", util)

            if bytes_read and max_speed and max_speed > 0:
                util = bytes_read / max_speed * 100.0
                port.set_metric_value("bytesReadUtilizationMax", util)
            if bytes_write and max_speed and max_speed > 0:
                util = bytes_write / max_speed * 100.0
                port.set_metric_value("bytesWriteUtilizationMax", util)

            # Check for property availability
            _check_for_property(props, "hasPortOps", port, ["opsTotal"])
            _check_for_property(props, "hasPortBytesRead", port, ["bytesRead"])
            _check_for_property(props, "hasPortBytesWrite", port, ["bytesWrite"])
            _check_for_property(props, "hasPortBytes", port, ["bytesTotal"])

            # check separately, either one will enable to "has" property
            _check_for_property(props, "hasPortUtilization", port, ["bytesReadUtilization"])
            _check_for_property(props, "hasPortUtilization", port, ["bytesWriteUtilization"])
            _check_for_property(props, "hasPortUtilizationMax", port, ["bytesReadUtilizationMax"])
            _check_for_property(props, "hasPortUtilizationMax", port, ["bytesWriteUtilizationMax"])

            # There are a bunch of places we roll up these metrics
            #   1. the container on the array itself (that's easy, it's the holder we using now)
            _port_roll_up_to_container(port, holder)
            #   2. the container on the associated controller (not so easy)
            controller = port.get_property("controller")
            if controller:
                try:
                    controller = update.get_object(controller)
                    controller_container = controller.get_property(key)
                    if controller_container:
                        controller_container = update.get_object(controller_container)

                    _port_roll_up_to_container(port, controller_container)
                except:
                    pass

            #   3. another place we don't support yet.
            
        array.set_metric_value(holders[key], failed["busted"])
        if failed["total"] > 0:
            array.set_metric_value(holders[key] + "_pct",
                                   (failed["busted"] / failed["total"] * 100.0))


def performance_post_processor(update, model, frequency):
    """
    Does the performance post processing on the provided model.

    .. warning:: This method is not intended to be called directly.

    :param update:
    :param model:
    :param frequency:
    """
    _logger.debug("Starting performance post-processing")

    key = foglight.topology.make_object_key("SanStorageArrays",
                                            {"name": "SanStorageArrays"})
    try:
        arrays = update.get_object(key)
    except:
        return

    if arrays:
        arrays = arrays.get_property("storageArrays", [])

    for array in arrays:

        # convert from key to object
        try:
            array = update.get_object(array)
        except:
            continue

        # In this version of the topology definition, the has* properties
        # are actually set during topology. We while we have to calculate them
        # based on performance data, we cannot submit then until the next topology
        # submission.
        props = _load_provider_properties(array.key)

        # Clear out any existing values
        props = dict.fromkeys(props, False)

        array.set_frequency(frequency)
        _disk_roll_up(array, props, update, frequency)
        _lun_roll_up(array, props, update, frequency)
        _pool_roll_up(array, props, update, frequency)
        _port_roll_up(array, props, update, frequency)
        _controller_roll_up(array, props, update, frequency)
        # Fill in all the discovered properties
        props["hasLunRebuilding"] = True

        #
        # Cache the properties (deprecated) for submission during topology/inventory collections.
        #
        # That is the old method of submitting the "has*" values, and is
        # deprecated in FSM 4.4 and later. We're using both methods for now
        # so that older Python-based storage agents remain forward compatible.
        #
        _save_provider_properties(array.key, props)

        #
        # The new method, shown here it to build a data object and place it in an observation
        #
        props_observation = update.create_data_object("SanProviderProperties", props)
        array.set_observation_value("properties", props_observation)

