# smisarray
This is a generic python agent to collect inventory and performance data from any SAN Storage Array that support SMI-S and submit to FSM (Foglight™ for Storage Management).

Foglight™ for Storage Management provides complete monitoring of virtual storage environments, providing performance and capacity management metrics. It is designed for customers requiring storage monitoring functionality, but not full-fledged virtualization environment monitoring functionality.

The inventory objects to be collected by the agent is listed as below,
* SanStorageArray
* SanController
* SanStorageSupplierPort
* SanPool
* SanPhysicalDisk
* SanLun

The performance metrics to be collected by the agent is listed as below,
* Controller
	* Highest Data Rate
	* Most Operations
	* Status
	* State
	* Date Rate
	* Ops Rate
	* Latency
	* Fc Port Status
	* IP port Status
* Port
	* FC Ports-Utilization Distribution
	* Status
	* Physical State
	* Data Rate
	* Ops Rate
* Pool
	* Ops Rate
	* Data Rate
	* Status
	* Total Raw Capacity
* Lun
	* r/w Latency
	* % busy
	* Ops rate
	* Data Rate
	* Cache hit rate
	* Status
	* Physical State
* Disk
	* % busy
	* Ops rate
	* Data Rate
	* Status
	* Physical State








