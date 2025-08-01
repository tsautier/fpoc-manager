from django.core.handlers.wsgi import WSGIRequest
from django.shortcuts import render
from django.http import HttpResponse

import copy

import fpoc
from fpoc.devices import Interface, FortiGate, LXC
from fpoc.FortiPoCSDWAN import FortiPoCSDWAN, FortiLabSDWAN, FabricStudioSDWAN
from fpoc.typing import TypePoC
import typing

import ipaddress


def dualdc(request: WSGIRequest) -> HttpResponse:
    """
    Dual-Region WEST/EAST
    WEST: Dual DC, Two Branches
    EAST: Single DC, One Branch
    """

    context = {
        # From HTML form
        'remote_internet': request.POST.get('remote_internet'),  # 'none', 'mpls', 'all'
        'bidir_sdwan': request.POST.get('bidir_sdwan'),  # 'none', 'route_tag', 'remote_sla', 'route_priority',
        'cross_region_advpn': bool(request.POST.get('cross_region_advpn', False)),  # True or False
        'full_mesh_ipsec': bool(request.POST.get('full_mesh_ipsec', False)),  # True or False
        'vrf_aware_overlay': bool(request.POST.get('vrf_aware_overlay', False)),  # True or False
        'advpnv2': bool(request.POST.get('advpnv2', False)),  # True or False
        'vrf_wan': int(request.POST.get('vrf_wan')),  # [0-251] VRF for Internet and MPLS links
        'vrf_pe': int(request.POST.get('vrf_pe')),  # [0-251] VRF for IPsec tunnels
        'vrf_blue': int(request.POST.get('vrf_blue')),  # [0-251] port5 (no vlan) segment
        'vrf_yellow': int(request.POST.get('vrf_yellow')),  # [0-251] vlan segment
        'vrf_red': int(request.POST.get('vrf_red')),  # [0-251] vlan segment
        'multicast': bool(request.POST.get('multicast', False)),  # True or False
        'br2br_routing': request.POST.get('br2br_routing'),  # 'strict_overlay_stickiness', 'hub_side_steering', 'fib'
        'shortcut_routing': request.POST.get('shortcut_routing'),  # 'no_advpn', 'exchange_ip', 'ipsec_selectors', 'dynamic_bgp'
        'bgp_design': request.POST.get('bgp_design'),  # 'per_overlay', 'per_overlay_legacy', 'on_loopback', 'no_bgp'
        'overlay': request.POST.get('overlay'),  # 'static' or 'mode_cfg'

        #
        'regional_advpn': None,  # 'boolean' defined later
        'bgp_route_reflection': None,  # 'boolean' defined later
        'bgp_aggregation': None,  # 'boolean' defined later
    }

    # Create the poc
    if 'fortipoc' in request.path:  # poc is running in FortiPoC
        poc = FortiPoCSDWAN(request)
    elif 'fabric'  in request.path:  # poc is running in FabricStudio
        poc = FabricStudioSDWAN(request)
    else:  # poc is running in Hardware Lab
        poc = FortiLabSDWAN(request)

    # Define the poc_id based on the options which were selected

    poc_id = None
    messages = []    # list of messages displayed along with the rendered configurations
    errors = []     # List of errors

    targetedFOSversion = FortiGate.FOS_int(request.POST.get('targetedFOSversion') or '0.0.0') # use '0.0.0' if empty targetedFOSversion string, FOS version becomes 0
    minimumFOSversion = 0

    if context['shortcut_routing'] == 'ipsec_selectors':
        minimumFOSversion = max(minimumFOSversion, 7_002_000)
    if context['vrf_aware_overlay']:
        minimumFOSversion = max(minimumFOSversion, 7_002_000)
    if context['bidir_sdwan'] == 'remote_sla':
        minimumFOSversion = max(minimumFOSversion, 7_002_001)
    if context['shortcut_routing'] == 'dynamic_bgp':
        minimumFOSversion = max(minimumFOSversion, 7_004_001)
    if context['advpnv2']:
        minimumFOSversion = max(minimumFOSversion, 7_004_002)

    if context['shortcut_routing'] == 'no_advpn':
        context['regional_advpn'] = context['cross_region_advpn'] = False
        context['bgp_route_reflection'] = False
        context['bgp_aggregation'] = True

    if context['shortcut_routing'] in ('ipsec_selectors', 'dynamic_bgp'):
        context['regional_advpn'] = True
        context['bgp_route_reflection'] = False
        context['bgp_aggregation'] = True

    if context['shortcut_routing'] == 'exchange_ip':
        context['regional_advpn'] = True
        context['bgp_route_reflection'] = True
        if context['cross_region_advpn']:
            context['bgp_aggregation'] = False
        else:
            context['bgp_aggregation'] = True

    if context['advpnv2']:
        if context['br2br_routing'] != 'fib':
            context['br2br_routing'] = 'fib'
            messages.append("ADVPN v2.0 no longer need any form of branch-to-branch routing strategy on the Hub. "
                            "So <b>Hub's br-2-br is forced to 'Simple FIB lookup'</b>")
    else:
        if context['shortcut_routing'] in ('ipsec_selectors', 'dynamic_bgp') and context['br2br_routing'] in ('strict_overlay_stickiness', 'fib'):
            messages.append(f"INET1 to INET2 shortcut failover on remote SLA failure requires <b>forcing</b> Hub's "
                            f"branch-to-branch routing to <b>hub_side_steering</b>. This is because the shortcut routing"
                            f" is independent from the Hub routing so the \"shortcut does not hide its parent\"")
            context['br2br_routing'] = 'hub_side_steering'

    if context['shortcut_routing'] == 'dynamic_bgp' and not context['cross_region_advpn']:
        context['cross_region_advpn'] = True
        messages.append("cross_region_advpn is <b>forced</b> because dynamic BGP over shortcuts is used"
                        "<br>Need to test if cross-region shortcuts can be controlled with network-id and auto-discovery-crossover")

    if context['shortcut_routing'] == 'ipsec_selectors':
        if not context['advpnv2']:
            messages.append("<b>Shortcut failover</b> on remote SLA failure is <b>only possible between INET1 and INET2</b>. "
                            "It is <b>not possible between INET and MPLS</b>")
        if context['cross_region_advpn']:
            messages.append("Cross-regional branch-to-remoteHub shortcut routing <b>cannot be done with IPsec selectors</b>. See comments with CLI settings.")
        if context['vrf_aware_overlay']:
            context['vrf_aware_overlay'] = False  # shortcuts from ph2 selectors are incompatible with vpn-id-ipip
            messages.append("VRF-aware overlay was requested but is <b>forced to disable</b> since it is not supported with shortcuts from phase2 selectors")

    #
    # PoC 6 #####

    if context['bgp_design'] == 'per_overlay_legacy':  # BGP per overlay, legacy 6.4+ style
        poc_id = 6
        minimumFOSversion = max(minimumFOSversion, 6_004_000)

    #
    # PoC 9 #####

    if context['bgp_design'] == 'per_overlay':  # BGP per overlay, 7.0+ style
        poc_id = 9
        minimumFOSversion = max(minimumFOSversion, 7_000_000)

        if context['vrf_aware_overlay']:
            poc_id = None  # TODO
            errors.append("vrf_aware_overlay not yet available with BGP per overlay")

        if context['full_mesh_ipsec']:
            context['full_mesh_ipsec'] = False   # Full-mesh IPsec not implemented for bgp-per-overlay
            messages.append("Full-mesh IPsec not implemented for bgp-per-overlay: option is forced to 'False'")

        if context['br2br_routing'] == 'hub_side_steering':
            if context['bidir_sdwan'] == 'none':
                context['bidir_sdwan'] = 'route_priority'
                messages.append(f"Hub's branch-to-branch is set to '{context['br2br_routing']}' but Bidirectional SD-WAN is "
                                f"not set. <b>Forcing</b> bidirectional sd-wan to <b>'BGP priority'</b>")

            messages.append("'hub_side_steering' is only available for Hub's branch-to-branch routing within the same region. "
                            "It is not yet available for branch-to-remoteRegion where only strict_overlay_stickiness "
                            "is currently available over inter-regional tunnels")

        # if context['shortcut_routing'] == 'dynamic_bgp':
        #     errors.append("Dynamic BGP over shortcuts not yet available with BGP per overlay")

        if context['shortcut_routing'] == 'ipsec_selectors' and context['bidir_sdwan'] == 'remote_sla':
            context['bidir_sdwan'] = 'route_priority'
            messages.append("ADVPN from IPsec selectors <b>DOES NOT WORK with</b> bgp-per-overlay and <b>remote-sla</b>"
                            " (see comment in code). <b>Forcing 'BGP priority'</b>")

        if context['bidir_sdwan'] == 'remote_sla':
            context['overlay'] = 'static'   # remote-sla with bgp-per-overlay can only work with static-overlay IP@
            messages.append("Bidirectional SDWAN with 'remote-sla' was requested: <b>overlay is therefore forced to 'static'</b> since "
                           "remote-sla with bgp-per-overlay can only work with static-overlay IP@")

    #
    # PoC 10 #####

    if context['bgp_design'] == 'on_loopback':  # BGP on loopback, as of 7.0.4
        poc_id = 10
        minimumFOSversion = max(minimumFOSversion, 7_000_004)

        if context['bidir_sdwan'] in ('route_tag', 'route_priority'):  # 'or'
            context['bidir_sdwan'] = 'remote_sla'  # route_tag and route_priority only works with BGP per overlay
            messages.append("Bi-directional SD-WAN was requested: <b>method was forced to 'remote-sla'</b> which is the only "
                           "supported method with bgp-on-loopback")

        if context['br2br_routing'] == 'hub_side_steering' and context['bidir_sdwan'] == 'none':
            context['bidir_sdwan'] = 'remote_sla'
            messages.append(f"Hub's branch-to-branch is set to '{context['br2br_routing']}' but Bidirectional SD-WAN is "
                            f"not set. <b>Forcing</b> bidirectional sd-wan to <b>'remote-sla'</b>")

        if not context['multicast']:
            context['overlay'] = None   # Unnumbered IPsec tunnels are used if there is no need for multicast routing
            messages.append("Multicast is not requested: unnumbered IPsec tunnels are used")
        else:
            messages.append(f"Multicast is requested: <b>IPsec tunnels are numbered with '{context['overlay']}' overlay</b>")
            if context['vrf_aware_overlay']:
                messages.append(f"for multicast to work <b>PE VRF and BLUE VRF are forced to VRF 0</b>")
                context['vrf_pe'] = context['vrf_blue'] = 0

        if context['vrf_aware_overlay']:
            for vrf_name in ('vrf_wan', 'vrf_pe', 'vrf_blue', 'vrf_yellow', 'vrf_red'):
                if context[vrf_name] > 251 or context[vrf_name] < 0:
                    poc_id = None; errors.append('VRF id must be within [0-251]')
            if context['vrf_pe'] in (context['vrf_yellow'], context['vrf_red']):
                poc_id = None; errors.append("Only seg0/BLUE VRF can be in the same VRF as the PE VRF")
            ce_vrfids = [context['vrf_blue'], context['vrf_yellow'], context['vrf_red']] # list of all CE VRF IDs
            if len(set(ce_vrfids)) != len(ce_vrfids):  # check if the CE VRF IDs are all unique
                poc_id = None; errors.append('All CE VRF IDs must be unique')

            if context['cross_region_advpn'] and context['shortcut_routing'] == 'exchange_ip':
                context['cross_region_advpn'] = False
                messages.append("Cross-Regional ADVPN based off BGP NH convergence was requested but <b>this does not work</b> with VPNv4 eBGP next-hop-unchanged (tested with FOS 7.2.5)"
                                "<br>The BGP NH of VPNv4 prefixes is always set to the BGP loopback of the DC when advertised to eBGP peer"
                                "<br>inter-regional branch-to-branch manages to flow via the regional Hubs"
                                "<br>but inter-regional branch-to-DC traffic <b>breaks</b> once the branch-to-remoteHub shortcut is created (RPF issue on Hub)"
                                "<br>consequently, <b>cross-regional ADVPN is forced to 'disable'</b> with VRF segmentation and ADVPN from BGP NextHop")

            if context['bgp_route_reflection']:
                messages.append("design choice: BGP Route-reflection (for ADVPN) is done only for VRFs BLUE and YELLOW. No RR (no ADPVPN) for VRF RED")

            messages.append("design choice: CE VRFs of WEST-BR1/BR2 have DIA while there is no DIA for the CE VRFs of EAST-BR1 (only RIA)")

    #
    # PoC x #####

    if context['bgp_design'] == 'no_bgp':  # No BGP, as of 7.2
        minimumFOSversion = max(minimumFOSversion, 7_002_000)
        poc_id = None   # TODO
        errors.append("SD-WAN+ADVPN design without BGP is not yet available")

    if poc_id is None:
        return render(request, f'fpoc/message.html',
                      {'title': 'Error', 'header': 'Error', 'message': errors})

    if targetedFOSversion and minimumFOSversion > targetedFOSversion:
        return render(request, f'fpoc/message.html',
                      {'title': 'Error', 'header': 'Error', 'message': f'The minimum version for the selected options is {minimumFOSversion:_}'})

    messages.insert(0, f"Minimum FortiOS version required for the selected set of features: {minimumFOSversion:_}")

    #
    # LAN underlays
    #

    LAN = {
        'WEST-DC1': Interface(address='10.1.0.1/24'),
        'WEST-DC2': Interface(address='10.2.0.1/24'),
        'WEST-BR1': Interface(address='10.0.1.1/24'),
        'WEST-BR2': Interface(address='10.0.2.1/24'),
        'EAST-DC1': Interface(address='10.4.0.1/24'),
        'EAST-BR1': Interface(address='10.4.1.1/24'),
        'EAST-DC3': Interface(address='10.3.0.1/24'),
        'EAST-BR3': Interface(address='10.0.3.1/24'),
    }

    # DataCenters info used:
    # - by DCs:
    #   - as underlay interfaces IP@ for inter-regional tunnels (inet1/inet2/mpls)
    # - by the Branches:
    #   - as IPsec remote-gw IP@ (inet1/inet2/mpls)
    # - by both DCs and Branches:
    #   - as part of the computation of the networkid for Edge IPsec tunnels (id)

    dc_loopbacks = {
        'WEST-DC1': '10.200.1.254',
        'WEST-DC2': '10.200.1.253',
        'EAST-DC1': '10.200.2.254',
        'EAST-DC2': '10.200.2.253',
    }

    # Name and id of EAST devices is different between poc10 and other pocs (poc9, poc7)
    if poc_id == 10:  # PoC with BGP on loopback design: Regional LAN summaries are possible
        east_dc_ = {'name': 'EAST-DC1', 'generic_name': 'EAST-DC', 'dc_id': 1, 'lxc': 'PC-EAST-DC1'}
        east_br_ = {'name': 'EAST-BR1', 'generic_name': 'EAST-BR', 'branch_id': 1, 'lxc': 'PC-EAST-BR1'}
    else:  # Other PoCs with BGP per overlay design: No Regional LAN summaries (IP plan would overlap between Region)
        east_dc_ = {'name': 'EAST-DC3', 'generic_name': 'EAST-DC', 'dc_id': 3, 'lxc': 'PC-EAST-DC3'}
        east_br_ = {'name': 'EAST-BR3', 'generic_name': 'EAST-BR', 'branch_id': 3, 'lxc': 'PC-EAST-BR3'}

    west_dc1_ = {
                    'id': 1,
                    'inet1': poc.devices['WEST-DC1'].wan.inet1,
                    'inet2': poc.devices['WEST-DC1'].wan.inet2,
                    'mpls': poc.devices['WEST-DC1'].wan.mpls1,
                    'lan': LAN['WEST-DC1'],
                    'loopback': dc_loopbacks['WEST-DC1']
                }

    west_dc2_ = {
                    'id': 2,
                    'inet1': poc.devices['WEST-DC2'].wan.inet1,
                    'inet2': poc.devices['WEST-DC2'].wan.inet2,
                    'mpls': poc.devices['WEST-DC2'].wan.mpls1,
                    'lan': LAN['WEST-DC2'],
                    'loopback': dc_loopbacks['WEST-DC2']
                }

    east_dc1_ = {
                    'id': 3,
                    'inet1': poc.devices['EAST-DC'].wan.inet1,
                    'inet2': poc.devices['EAST-DC'].wan.inet2,
                    'mpls': poc.devices['EAST-DC'].wan.mpls1,
                    'lan': LAN[east_dc_['name']],
                    'loopback': dc_loopbacks['EAST-DC1']
                }

    east_dc2_ = {  # Fictitious second DC for East region
                    'id': 4,
                    'inet1': poc.devices['EAST-DC'].wan.inet1,
                    'inet2': poc.devices['EAST-DC'].wan.inet2,
                    'mpls': poc.devices['EAST-DC'].wan.mpls1,
                    'lan': '0.0.0.0',
                    'loopback': dc_loopbacks['EAST-DC2']
                }

    datacenters = {
            'west': {
                'first': west_dc1_,
                'second': west_dc2_,
            },
            'east': {
                'first': east_dc1_,
                'second': east_dc2_,  # Fictitious second DC for East region
            }
        }

    rendezvous_points = {}
    if context['multicast']:
        rendezvous_points = {
            'WEST-DC1': dc_loopbacks['WEST-DC1'],
            'WEST-DC2': dc_loopbacks['WEST-DC2'],
            'EAST-DC1': dc_loopbacks['EAST-DC1'],   # used by PoC10 only
            'EAST-DC3': dc_loopbacks['EAST-DC1'],   # used by PoC9 only
        }

    # merge dictionaries
    context = {
        **context,
        'rendezvous_points': rendezvous_points
    }

    #
    # FortiGate Devices

    west_dc1 = FortiGate(name='WEST-DC1', template_group='DATACENTERS',
                         lan=LAN['WEST-DC1'],
                         template_context={'region': 'West', 'region_id': 1, 'dc_id': 1, 'gps': (48.856614, 2.352222),
                                           'loopback': dc_loopbacks['WEST-DC1'],
                                           'datacenter': datacenters,
                                           **context})
    west_dc2 = FortiGate(name='WEST-DC2', template_group='DATACENTERS',
                         lan=LAN['WEST-DC2'],
                         template_context={'region': 'West', 'region_id': 1, 'dc_id': 2, 'gps': (50.1109221, 8.6821267),
                                           'loopback': dc_loopbacks['WEST-DC2'],
                                           'datacenter': datacenters,
                                           **context})
    west_br1 = FortiGate(name='WEST-BR1', template_group='BRANCHES',
                         lan=LAN['WEST-BR1'],
                         template_context={'region': 'West', 'region_id': 1, 'branch_id': 1, 'gps': (44.8333, -0.5667),
                                           'loopback': '10.200.1.1',
                                           'datacenter': datacenters['west'],
                                           **context})
    west_br2 = FortiGate(name='WEST-BR2', template_group='BRANCHES',
                         lan=LAN['WEST-BR2'],
                         template_context={'region': 'West', 'region_id': 1, 'branch_id': 2, 'gps': (43.616354, 7.055222),
                                           'loopback': '10.200.1.2',
                                           'datacenter': datacenters['west'],
                                           **context})
    east_dc = FortiGate(name=east_dc_['name'], template_group='DATACENTERS',
                        lan=LAN[east_dc_['name']],
                        template_context={'region': 'East', 'region_id': 2, 'dc_id': east_dc_['dc_id'], 'gps': (52.2296756, 21.0122287),
                                          'loopback': dc_loopbacks['EAST-DC1'],
                                           'datacenter': datacenters,
                                           **context})
    east_br = FortiGate(name=east_br_['name'], template_group='BRANCHES',
                        lan=LAN[east_br_['name']],
                        template_context={'region': 'East', 'region_id': 2, 'branch_id': east_br_['branch_id'], 'gps': (47.497912, 19.040235),
                                          'loopback': '10.200.2.1',
                                           'datacenter': datacenters['east'],
                                           **context})

    #
    # Host Devices used to build the /etc/hosts file

    hosts = {
        'PC-WEST-DC1': {'rank': 7, 'gateway': LAN['WEST-DC1'].ipprefix},
        'PC-WEST-DC2': {'rank': 7, 'gateway': LAN['WEST-DC2'].ipprefix},
        'PC-EAST-DC1': {'rank': 7, 'gateway': LAN['EAST-DC1'].ipprefix},
        'PC-EAST-DC3': {'rank': 7, 'gateway': LAN['EAST-DC3'].ipprefix},
        'PC-WEST-BR1': {'rank': 101, 'gateway': LAN['WEST-BR1'].ipprefix},
        'PC-WEST-BR2': {'rank': 101, 'gateway': LAN['WEST-BR2'].ipprefix},
        'PC-EAST-BR1': {'rank': 101, 'gateway': LAN['EAST-BR1'].ipprefix},
        'PC-EAST-BR3': {'rank': 101, 'gateway': LAN['EAST-BR3'].ipprefix},
    }

    devices = {
        'WEST-DC1': west_dc1,
        'WEST-DC2': west_dc2,
        'EAST-DC': east_dc,     # 'DC' and not 'DC1' because it references the device in class FortiPoCSDWAN
        'WEST-BR1': west_br1,
        'WEST-BR2': west_br2,
        'EAST-BR': east_br,     # 'BR' and not 'BR1' because it references the device in class FortiPoCSDWAN

        'PC-WEST-DC1': LXC(name="PC-WEST-DC1", template_context={'hosts': hosts}),
        'PC-WEST-DC2': LXC(name="PC-WEST-DC2",template_context={'hosts': hosts}),
        'PC-EAST-DC': LXC(name=east_dc_['lxc'], template_context={'hosts': hosts}),   # DC and not DC1
        'PC-WEST-BR1': LXC(name="PC-WEST-BR1",template_context={'hosts': hosts}),
        'PC-WEST-BR2': LXC(name="PC-WEST-BR2",template_context={'hosts': hosts}),
        'PC-EAST-BR': LXC(name=east_br_['lxc'], template_context={'hosts': hosts}),   # BR and not BR1
        'INTERNET-SERVER': LXC(name="INTERNET-SERVER", template_filename='lxc_SRV_INET.conf')
    }

    # Add VRF segmentation information to the poc
    #
    if context['vrf_aware_overlay']:
        vrf_segmentation(context, poc, devices)

        # Create a callback function to check if VDOMs must be enabled on FGT appliances with NPU ASIC
        # when VRF segmentation is done

        # As of 7.6.1, multi-vdom is no longer needed for VRF segmentation. So, the callback must now be registered at
        # the device level (which contains the FOS version) rather than at the poc level
        def multi_vdom(fgt: FortiGate):
            fgt.template_context['multi_vdom'] = not fgt.FOS >= 7_006_001   # multi-vdom no longer needed as of 7.6.1

        # Register the callback function for each NPU FGT in the 'devices' dict
        # Do not register the callback on poc.devices because at this stage these are the devices of the class itself
        # So the callback must be registered to the 'devices' in the dict
        # The dict 'devices' do not have the NPU info, so need to get this info from the class 'devices' (poc.devices)
        for devname, device in devices.items():
            if isinstance(device, FortiGate) and poc.devices[devname].npu:
                    device.callback_register(multi_vdom)

        # Before 7.6.1, the callback was done at poc level since all devices had to enable vdoms for VRF segmentation
        # def multi_vdom(poc: TypePoC):
        #     for fortigate in [device for device in poc.devices.values() if isinstance(device, FortiGate)]:
        #         fortigate.template_context['multi_vdom'] = bool(fortigate.npu)
        #
        # # Register the callback function
        # poc.callback_register(multi_vdom)

    # Update the poc
    poc.id = poc_id
    poc.minimum_FOS_version = minimumFOSversion
    poc.messages = messages

    # Check request, render and deploy configs
    return fpoc.start(poc, devices)


###############################################################################################################
#
# VRF segmentation
#

# About VRF IDs (from Dmitry 'Managed SDWAN' workshop):
#
# The choice of PE VRF=1 is not completely arbitrary. While generally any non-zero PE VRF would work, we
# recommend using PE VRF=1 whenever possible, because it optimizes local-out traffic flows in some
# scenarios. While the detailed discussion is not in scope of this lab, we will simply mention that in certain
# situations the local-out traffic (such as the communication with FortiManager, FortiGuard and so on) may
# be taking an extra hop inside the FortiGate device, if the Internet VRF (which is the PE VRF!) has an ID
# higher than a CE VRF.
# Exactly for this reason the optimal configuration is when VRF=0 is not used, VRF=1 is configured as PE
# and the rest is left to CEs.
#
def vrf_segmentation(context: dict, poc: TypePoC, devices: typing.Mapping[str, typing.Union[FortiGate, LXC]]) -> None:
    vrf = {
        'LAN': { 'vrfid': context['vrf_blue'], 'vlanid': 0, 'alias': 'LAN_BLUE' },
        'SEG_YELLOW': { 'vrfid': context['vrf_yellow'], 'alias': 'LAN_YELLOW' },
        'SEG_RED': { 'vrfid': context['vrf_red'], 'alias': 'LAN_RED' },
    }

    segments = {
        'WEST-DC1': {
            'LAN': Interface(address='10.1.0.1/24', **vrf['LAN']),
            'SEG_YELLOW': Interface(address='10.1.1.1/24', vlanid=16, **vrf['SEG_YELLOW']),
            'SEG_RED': Interface(address='10.1.2.1/24', vlanid=17, **vrf['SEG_RED']),
        },
        'WEST-DC2': {
            'LAN': Interface(address='10.2.0.1/24', **vrf['LAN']),
            'SEG_YELLOW': Interface(address='10.2.1.1/24', vlanid=26, **vrf['SEG_YELLOW']),
            'SEG_RED': Interface(address='10.2.2.1/24', vlanid=27, **vrf['SEG_RED']),
        },
        'WEST-BR1': {
            'LAN': Interface(address='10.0.1.1/24', **vrf['LAN']),
            'SEG_YELLOW': Interface(address='10.0.11.1/24', vlanid=36, **vrf['SEG_YELLOW']),
            'SEG_RED': Interface(address='10.0.12.1/24', vlanid=37, **vrf['SEG_RED']),
        },
        'WEST-BR2': {
            'LAN': Interface(address='10.0.2.1/24', **vrf['LAN']),
            'SEG_YELLOW': Interface(address='10.0.21.1/24', vlanid=46, **vrf['SEG_YELLOW']),
            'SEG_RED': Interface(address='10.0.22.1/24', vlanid=47, **vrf['SEG_RED']),
        },
        'EAST-DC': {
            'LAN': Interface(address='10.4.0.1/24', **vrf['LAN']),
            'SEG_YELLOW': Interface(address='10.4.1.1/24', vlanid=56, **vrf['SEG_YELLOW']),
            'SEG_RED': Interface(address='10.4.2.1/24', vlanid=57, **vrf['SEG_RED']),
        },
        'EAST-BR': {
            'LAN': Interface(address='10.4.1.1/24', **vrf['LAN']),
            'SEG_YELLOW': Interface(address='10.4.11.1/24', vlanid=66, **vrf['SEG_YELLOW']),
            'SEG_RED': Interface(address='10.4.12.1/24', vlanid=67, **vrf['SEG_RED']),
        },
    }

    # 'inter_segments' describe the inter-vrf links used for DIA.
    # Allow segments in VRF x to access the Internet which is in VRF {{vrf_wan}}
    inter_segments = {
        'BLUE_': [ {'vrfid': context['vrf_wan'], 'ip': '10.254.254.2', 'mask':'255.255.255.254'},
                        {'vrfid': context['vrf_blue'], 'ip': '10.254.254.3', 'mask':'255.255.255.254'} ],
        'YELLOW_': [ {'vrfid': context['vrf_wan'], 'ip': '10.254.254.4', 'mask':'255.255.255.254'},
                        {'vrfid': vrf['SEG_YELLOW']['vrfid'], 'ip': '10.254.254.5', 'mask':'255.255.255.254'} ],
        'RED_': [ {'vrfid': context['vrf_wan'], 'ip': '10.254.254.6', 'mask':'255.255.255.254'},
                        {'vrfid': vrf['SEG_RED']['vrfid'], 'ip': '10.254.254.7', 'mask':'255.255.255.254'} ],
    }

    if context['vrf_blue'] == context['vrf_wan']:  # SEG0/port5 is in WAN VRF, it has direct access to WAN (INET)
        inter_segments.pop('BLUE_')  # remove it from the inter-segment list

    #
    # Update FortiGate devices
    #
    # 'direct_internet_access' setting is only for the CE VRF of the Branches. It does not apply to Hubs because
    # Hubs must have DIA in order to offer RIA service to its CE VRFs.

    for name in segments.keys():
        # devices[name].template_context['lan'].update(vrf['LAN'])
        devices[name].lan.update(segments[name]['LAN'])
        devices[name].template_context['vrf_segments'] = segments[name]
        devices[name].template_context['inter_segments'] = inter_segments
        devices[name].template_context['direct_internet_access'] = True

        # Update Host Devices
        devices[f'PC-{name}'].template_filename = 'lxc.vrf.conf'

    # Update EAST-BR: there is no DIA for EAST-BR
    devices['EAST-BR'].template_context['direct_internet_access'] = False
