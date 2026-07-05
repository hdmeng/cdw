from pysnmp.hlapi import *
import psutil
import socket
from pysnmp.smi import builder, view

#!/usr/bin/env python3
"""
SNMP Server - Provides system status and running processes information
"""


# Create SNMP engine
snmpEngine = SnmpEngine()

# Create MIB builder and view
mibBuilder = builder.MibBuilder()
mibView = view.MibViewController(mibBuilder)

# Create UDP transport on port 161
config.addTransport(
    snmpEngine,
    'udp',
    udp.openServerMode(('0.0.0.0', 161))
)

# Add community string
config.addV1System(snmpEngine, 'public')

# Get system status
def get_system_status():
    return {
        'hostname': socket.gethostname(),
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': psutil.disk_usage('/').percent,
        'boot_time': psutil.boot_time(),
    }

# Get running processes
def get_running_processes():
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'status']):
        try:
            processes.append({
                'pid': proc.info['pid'],
                'name': proc.info['name'],
                'status': proc.info['status']
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return processes

# SNMP callback function
def snmp_callback(snmpEngine, execSnmpUsmUserEngineID, contextEngineId,
                  varBinds, **options):
    varBinds = []
    status = get_system_status()
    
    varBinds.append(ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0),
                               f"System: {status['hostname']}"))
    varBinds.append(ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysUpTime', 0),
                               int(status['boot_time'])))
    
    return cbCtx.copyContextVars(varBinds=varBinds)

# Main loop
def start_snmp_server():
    print("SNMP Server starting on port 161...")
    print("System Status:", get_system_status())
    print(f"Running Processes: {len(get_running_processes())}")
    
    snmpEngine.transportDispatcher.runDispatcher()

if __name__ == '__main__':
    start_snmp_server()