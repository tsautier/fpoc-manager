import re, netmiko, paramiko
from netmiko import NetmikoAuthenticationException
import scp as scp_

from fpoc.devices import FortiGate
from fpoc.exceptions import StopProcessingDevice


def ssh_logon(device: FortiGate):
    """
    Login to FGT via SSH

    :param device:
    :return: ssh handler
    """
    ssh_params = {
        'ip': device.ip,
        'username': device.username,
        'password': device.password,
        'device_type': 'fortinet',
        'port': device.ssh_port,
        # 'verbose': True,
        # 'conn_timeout': 1,
        # 'auth_timeout': 1,
        # 'banner_timeout': 1,
        # 'blocking_timeout': 1,
        # 'timeout': 1,
        # 'session_timeout': 1,
        # 'auto_connect': True,
    }

    # print(netmiko_dict)

    # SSH connection to the FGT
    password_list = [ssh_params['password'], 'fortinet', '']
    for pwd in password_list:
        ssh_params['password'] = pwd
        try:
            ssh = netmiko.ConnectHandler(**ssh_params)
        except NetmikoAuthenticationException:
            print(f'{device.name} : SSH authentication failed with password "{pwd}". Trying with next password...')
            continue
            # ssh = netmiko.ConnectHandler(**ssh_params)
        else:
            print(f'{device.name} : Successful SSH authentication with password "{pwd}"')
            break

    return ssh

# Used as backup solution if there is a failure of the API authentication based on username-password
def create_api_admin(device: FortiGate):
    """
    Create an API admin and retrieve an API key for this admin
    REQUIRES to ALTER the netmiko class for 'fortinet'
    => comment all code in FortinetSSH.session_preparation() method: only keep a 'pass' statement

    :param device:
    :return:
    """

    ssh = ssh_logon(device)

    # Check if there is an API admin already configured on this device
    device.output = ssh.send_command(f'get sys api-user | grep "name: {device.apiadmin}"')
    if device.output.strip() != f'name: {device.apiadmin}':  # API admin is not configured on the device
        # Create API admin
        cli_commands = f'''
        config system api-user
            edit "{device.apiadmin}"
                set accprofile "super_admin"
                set vdom "root"
                config trusthost
                    edit 1
                        set ipv4-trusthost {device.mgmt.network}
                    next
                end
            next
        end    
        '''
        device.output += ssh.send_config_set(cli_commands.splitlines())

    # Generate and retrieve the API key for the API admin
    output_generate_apikey = ssh.send_command('exec api-user generate-key adminapi')
    re_token = re.search('New API key:(.+)', output_generate_apikey, re.IGNORECASE)

    if not re_token:  # API key failed to be retrieved => skip this device
        raise StopProcessingDevice(f'device={device.name} : failure to create the API admin or to retrieve '
                                   f'the API key')

    # Update the apikey for this FGT
    device.apikey = re_token.group(1).strip()

    # Store the output of the SSH session (can be useful for debugging)
    device.output += output_generate_apikey


def upload_firmware(device: FortiGate, firmware: str):
    """
    Update (upgrade or downgrade) the firmware of this FGT

    :param device:
    :param firmware: filename of the firmware to be uploaded to the FGT
    :return:
    """
    ssh = paramiko.SSHClient()
    # ssh.load_system_host_keys()   # Do not load system host jeys otherwise it can trigger paramiko.ssh_exception.BadHostKeyException
    ssh.set_missing_host_key_policy(paramiko.WarningPolicy())   # Accept unknown server key, simply log a warning
    ssh.connect(hostname=device.ip, username=device.username, password=device.password, port=device.ssh_port)

    scp = scp_.SCPClient(ssh.get_transport())   # SCPCLient takes a paramiko transport as an argument

    # Upload firmware
    scp.put(remote_path='fgt-image', files=firmware)

    # close connections
    scp.close(); ssh.close()

# Legacy functions for old FOS versions (< 7.0) #####################

def retrieve_hostname(device: FortiGate) -> str:
    """

    :param device:
    :return:
    """
    ssh = ssh_logon(device)

    device.output = ssh.send_command('get system status')
    re_token = re.search('Hostname: (.+)', device.output, re.IGNORECASE)

    if not re_token:  # failed to retrieve hostname => skip this device
        raise StopProcessingDevice(f'device={device.name} : failure to retrieve the hostname via SSH')

    # Return the hostname
    return re_token.group(1).strip()


def is_running_ha(device: FortiGate) -> bool:
    """

    :param device:
    :return:
    """
    ssh = ssh_logon(device)

    device.output = ssh.send_command('get system status')
    re_token = re.search('Current HA mode: (.+)', device.output, re.IGNORECASE)

    if not re_token:  # failed to retrieve HA status => skip this device
        raise StopProcessingDevice(f'device={device.name} : failure to retrieve the HA status via SSH')

    # Return True if HA mode is not 'standalone', return False if HA mode is 'standalone'
    return re_token.group(1).strip() != 'standalone'
