from django.core.handlers.wsgi import WSGIRequest
from django.template import loader
from config.settings import BASE_DIR

import fpoc.ssh
import fpoc.fortipoc as fortipoc
from fpoc.devices import LXC
from fpoc.fortipoc import TypePoC

def deploy_config(request: WSGIRequest, poc: TypePoC, device: LXC):
    """
    Render the configuration (Django template) and deploy it

    :param request:
    :param scenario:
    :param device:
    :return:
    """

    # Render the config
    #

    template_name = f'fpoc/lxc.conf'
    device.config = loader.render_to_string(template_name, device.template_context, request)
    # print(cli_settings)

    # Save this CLI configuration script to disk
    # filename = f'{BASE_DIR}/templates/{template_base_path}/__{device.name}__.conf'
    # with open(filename, 'w') as f:
    #     f.write(device.config)

    # print(f'CLI configuration script saved to {filename}')

    # Deploy the config
    #
    if request.POST.get('previewOnly'):  # Only preview of the config is requested, no deployment needed
        return None  # No more processing needed for this FGT

    # Run the CLI settings on the LXC
    ssh_params = {
        'device_type': 'linux',
        'ip': device.ip,
        'username': device.username,
        'password': device.password,
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

    device.output = fpoc.ssh.send_config_set(ssh_params, device.config.splitlines())
    print(device.output)
