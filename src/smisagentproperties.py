# coding=utf-8
ASPs = {
"purestorage": {  #normal, no performance data provided
    'USERNAME' : 'pureuser',
    'PASSWORD' : 'pureuser',
    'SERVER_URL' : 'https://10.2.117.3:5989'
},
"huawei": {     #all data collected
    'USERNAME' : 'smis_admin',
    'PASSWORD' : 'Admin@12',
    'SERVER_URL' : 'https://100.115.125.202:5989'
},
"clariion": {   #all data collected
    'USERNAME': 'vtest',
    'PASSWORD': 'Password1',
    'SERVER_URL': 'http://10.6.153.31:5988'
},
"clariion1": {  #all data collected
    'USERNAME': 'vfs\\vtest',
    'PASSWORD': 'Password1',
    'SERVER_URL': 'http://10.6.151.65:5988'
},
"eva1": {       #all data collected
    'USERNAME': 'vtest',
    'PASSWORD': 'Password1',
    'SERVER_URL': 'http://10.6.151.20:5988'
},
"usp1": {       #normal, no stats for controller and disk provided, need Tunning Manager
    'USERNAME': 'system',
    'PASSWORD': 'manager',
    'SERVER_URL': 'https://10.6.153.41:5989'
},
"ams1": {       #normal, no stats for controller and disk provided, need Tunning Manager
    'USERNAME': 'system',
    'PASSWORD': 'manager',
    'SERVER_URL': 'https://10.6.153.33:5989'
},
"ams2": {       #normal, no stats for controller and disk provided, need Tunning Manager
    'USERNAME': 'vtest',
    'PASSWORD': 'Password1',
    'SERVER_URL': 'http://10.6.148.110:5988'
},
"vnxe": {       #no performance data
    'USERNAME': 'local/smilab',
    'PASSWORD': 'F00sb4ll#',
    'SERVER_URL': 'https://10.1.132.33:5989'
},
"vmax": {       #failed to connect
    'USERNAME': 'smilab6',
    'PASSWORD': 'F00sb4ll',
    'SERVER_URL': 'http://10.1.134.184:5988'
},
"fujitsu": {    # can get topology data,  failed to retrieve performance data due to connection problem
    'USERNAME': 'smilab',
    'PASSWORD': 'F00sb4ll',
    'SERVER_URL': 'https://10.1.134.136:5989'
}
}
AGENTNAME = 'vmax'