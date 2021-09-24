from django.urls import path

from fpoc import views, pocs

# The 'name' of the paths are used in templates (html) and must be unique across whole apps of the project
# By registering a name for this app with variable 'app_name' it creates a context
# In the templates, the name must be referenced with {% url '<app_name>:<path.name>' %}
app_name = 'fpoc'

urlpatterns = [
    path('', views.HomePageView.as_view(), name='home'),
    path('about/', views.AboutPageView.as_view(), name='about'),
    path('test/', views.display_request_parameters, name='display_request_parameters'),

    path('poc/0/', pocs.bootstrap, {'poc_id': 0}, name='bootstrap'),

    path('poc/1/', pocs.sdwan_simple, {'poc_id': 1}, name='sdwan_simple'),
    path('poc/5/', pocs.sdwan_advpn_bgp_per_overlay, {'poc_id': 5}, name='sdwan_advpn_bgp_per_overlay'),

    path('poc/2/', pocs.vpn_dialup, {'poc_id': 2}, name='vpn_dialup'),
    path('poc/3/', pocs.vpn_site2site, {'poc_id': 3}, name='vpn_site2site'),
    path('poc/4/', pocs.vpn_dualhub_singletunnel, {'poc_id': 4}, name='vpn_dualhub_singletunnel'),
]

# TODO list
"""
- suspend devices which are not used for a poc
  if a device is used for a poc and it is currently suspended, resume it

Usability:
----------
- once a config has been pushed to a device, store this new config in its revision history using poc_id
  would need to find a way to store info about 'context' as well
  --> tried in deploy_config() but the comment field is very limited in size so cannot write the whole 'context' there
  
- access the devices via a link provided by the config generator
  otherwise access is via FPoC and one have to remembver that FGT-1 in PoC is FGT-A in FUNDATION, etc...

- ensure that there is no need to enter an empty dependency like this one:
    device_dependencies = {
        'FGT-A': ('PC_A1', 'PC_A2'),
        'FGT-A_sec': ('PC_A1', 'PC_A2'),
        'ISFW-A': (),  <--------------------- HERE
        'FGT-B': ('PC_B1',),
        'FGT-C': ('PC_C1',)
    }

- Use class Form to store the context elements of a scenario and generate the HTML code with template where the 
  accordion are all created automatically  

- Enrich the print() statement with the Rich class
    RED color when device is skipped
    ORANGE color when retries
    GREEN color when device is finished processing
    Add the name of the device to the beginning of each line, similar to a debug => needed for threading

- Optimize device launch by using Threading
"""