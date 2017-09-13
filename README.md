# smisarray
This is a generic python agent to collect inventory and performance data from any SAN Storage Array that support SMI-S and submit to FSM (Foglight™ for Storage Management).

Foglight™ for Storage Management provides complete monitoring of virtual storage environments, providing performance and capacity management metrics. It is designed for customers requiring storage monitoring functionality, but not full-fledged virtualization environment monitoring functionality.

## What is SMI-S
The SMI-S, developed by the SMI organization of the SNIA, is an open standard used to manage storage networks of multiple vendors. The SMI-S defines a set of secure and reliable interfaces that help the storage management system identify, classify, and monitor physical and logical resources in a storage area network (SAN).
Based on the existing technical standards, the SMI-S covers:
	Common information model (CIM) - The CIM is developed by a distributed management task force (DMTF) to describe concept models of data. The CIM uses a layered object-oriented system structure to model for managed resources. Devices and components can thus be described in an object-oriented manner.
	Web-based enterprise management (WBEM) - The WBEM is an enterprise-class management system structure developed by a DMTF. The WBEM assembles management protocols and standard Internet technologies for unified management in a distributed operating environment, improving data exchange capabilities across technologies and platforms.
	Service location protocol (SLP) - The SLP is used to discover the SMI-S server and its functions in a storage network environment.
 
As an open standard, the SMI-S expands general-purpose capabilities of the CIM, WBEM, and SLP to achieve interoperability in a storage network environment. For example, the WBEM provides security, resource lock management, and event notification.


## What data could be collected

### The inventory objects to be collected by the agent is listed as below,
* SanStorageArray
* SanController
* SanStorageSupplierPort
* SanPool
* SanPhysicalDisk
* SanLun

### The performance metrics to be collected by the agent is listed as below,
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


## Monitoring approach
During this procedure, you configure the agent to use SMI-S to collect from the Array Management Host that monitors the arrays.
To configure an agent to monitor the storage device:
1	On the navigation panel, under Dashboards, click the Administration tab.  
2	Click the Agents tab, then the Agent Status tab
3	Click Deploy Agent Package. 
4	The Storage Device Setup Wizard opens. Each of the following steps corresponds to one page in the wizard. Use the Next and Back buttons to navigate between pages. 
a	On the Select Host Selector page, select the Host to host this agent. 
b	On the Select Agent Packages page, select SMISStorageAgent. 
c	On the Agent Configuration Summary page, review the agent configuration. You can go back and make corrections, if necessary. 
d	Click Finish. 
5	Click Create Agent to open in the wizard
6	The Storage Device Setup Wizard opens. Each of the following steps corresponds to one page in the wizard. Use the Next and Back buttons to navigate between pages. 
a	On the Select Host Selector page, select the Host to host this agent. 
b	On the Select Agent Type and Instance page, select SMISStorageAgent. 
c	On the Agent Configuration Summary page, review the agent configuration. You can go back and make corrections, if necessary. 
d	Click Finish. 
7	Select the Agent to configure, click Edit Properties.
8	Click Modify the private properties for this agent.
9	Edit the User-defined Properties
	Host: ip of the SMI-S,default 127.0.0.1
	Port: port of the SMI-S, default 5989
	Username: the user of the SMI-S
	Password: the password of the SMI-S
10	Click Save.
11	Select the Agent that you want to activate
12	Click Activate.


## Reference:
[1] Quest Foglight™ eDocs https://support.quest.com/Foglight™-for-virtualization-enterprise-edition/
[2] SNIA, SMI architecture https://www.snia.org/forums/smi/knowledge/smis-getting-started/smi_architecture
[3] SNIA, SMI Overview https://www.snia.org/sites/default/files/technical_work/SMIS/SMI-Sv1.6.1r6_Overview.book_.pdf




