# Copyright (c) 2018 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

COORDINATION = 'networking_ansible.ml2.mech_driver.coordination'
DRIVER_TAG = 'ansible:'
LLI = 'local_link_information'
NETWORKING_ENTITY = 'ANSIBLENETWORKING'
PHYSNET = 'provider:physical_network'

# values that will be cast to Bool in the conf process
BOOLEANS = ['manage_vlans', 'stp_edge']
# values that will be rolled into a separate dict and passed to network_runner
EXTRA_PARAMS = ['stp_edge']
