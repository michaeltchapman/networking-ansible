# Copyright (c) 2018 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
from neutron.objects import network
from neutron.objects import ports
from neutron.objects import trunk
from neutron.plugins.ml2 import driver_context
from oslo_config import cfg
from oslotest import base
import pbr
from tooz import coordination

from networking_ansible import config
from networking_ansible.ml2 import mech_driver

QUOTA_REGISTRIES = (
    "neutron.quota.resource_registry.unregister_all_resources",
    "neutron.quota.resource_registry.register_resource_by_name",
)

COORDINATION = 'networking_ansible.ml2.mech_driver.coordination'


def patch_neutron_quotas():
    """Patch neutron quotas.

    This is to avoid "No resource found" messages printed to stderr from
    quotas Neutron code.
    """
    for func in QUOTA_REGISTRIES:
        mock.patch(func).start()


class MockConfig(object):
    def __init__(self, host=None, mac=None):
        self.inventory = {host: {'mac': mac}} if host and mac else {}
        self.mac_map = {}


class BaseTestCase(base.BaseTestCase):
    test_config_files = []
    parse_config = True

    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        super(BaseTestCase, self).setUp()
        if self.parse_config:
            self.setup_config()

        self.ansconfig = config
        self.testhost = 'testhost'
        # using lowercase to ensure case sensitivity is handled correctly
        # the code applys upper() to everything
        self.testmac = '01:23:45:67:89:ab'
        self.testphysnet = 'physnet'

        self.m_config = MockConfig(self.testhost, self.testmac)

    def setup_config(self):
        """Create the default configurations."""
        version_info = pbr.version.VersionInfo('networking_ansible')
        config_files = []
        for conf in self.test_config_files:
            config_files += ['--config-file', conf]
        cfg.CONF(args=config_files,
                 project='networking_ansible',
                 version='%%(prog)s%s' % version_info.release_string())


class NetworkingAnsibleTestCase(BaseTestCase):
    def setUp(self):
        patch_neutron_quotas()
        super(NetworkingAnsibleTestCase, self).setUp()
        config_module = 'networking_ansible.ml2.mech_driver.config.Config'
        with mock.patch(config_module) as m_cfg:
            m_cfg.return_value = self.m_config
            self.mech = mech_driver.AnsibleMechanismDriver()
            with mock.patch(COORDINATION) as m_coord:
                m_coord.get_coordinator = lambda *args: mock.create_autospec(
                    coordination.CoordinationDriver).return_value
                self.mech.initialize()

        self.testsegid = '37'
        self.testsegid2 = '73'
        self.testport = 'switchportid'
        self.testid = 'aaaa-bbbb-cccc'

        # Define mocked network context
        self.mock_net_context = mock.create_autospec(
            driver_context.NetworkContext).return_value
        self.mock_net_context.current = {
            'id': 37,
            'provider:network_type': 'vlan',
            'provider:segmentation_id': self.testsegid,
            'provider:physical_network': self.testphysnet,
        }
        self.mock_net_context._plugin_context = 'foo'

        # mocked network orm object
        self.mock_net_obj = mock.create_autospec(
            network.Network).return_value
        self.mock_netseg_obj = mock.Mock(spec=network.NetworkSegment)
        self.mock_netseg_obj.segmentation_id = self.testsegid
        self.mock_netseg_obj.physical_network = self.testphysnet
        self.mock_netseg_obj.network_type = 'vlan'
        self.mock_net_obj.segments = [self.mock_netseg_obj]

        # alternative segment
        self.mock_netseg2_obj = mock.Mock(spec=network.NetworkSegment)
        self.mock_netseg2_obj.segmentation_id = self.testsegid2
        self.mock_netseg2_obj.physical_network = self.testphysnet
        self.mock_netseg2_obj.network_type = 'vlan'

        # non-physnet segment
        self.mock_netseg3_obj = mock.Mock(spec=network.NetworkSegment)
        self.mock_netseg3_obj.segmentation_id = self.testsegid2
        self.mock_netseg3_obj.physical_network = 'virtual'
        self.mock_netseg3_obj.network_type = 'vxlan'

        # define mocked port context
        self.mock_port_context = mock.create_autospec(
            driver_context.PortContext).return_value
        self.lli_no_mac = {
            'local_link_information': [{
                'switch_info': self.testhost,
                'port_id': self.testport,
            }]
        }
        self.lli_no_info = {
            'local_link_information': [{
                'switch_id': self.testmac,
                'port_id': self.testport,
            }]
        }
        self.mock_port_context.current = {
            'id': self.testid,
            'binding:profile': self.lli_no_mac,
            'binding:vnic_type': 'baremetal',
            'binding:vif_type': 'other',
            'mac_address': self.testmac
        }
        self.mock_port_context._plugin_context = mock.MagicMock()
        self.mock_port_context.network = mock.Mock()
        self.mock_port_context.network.current = {
            'id': self.testid,
            # TODO(radez) should an int be use here or str ok?
            'provider:network_type': 'vlan',
            'provider:segmentation_id': self.testsegid,
            'provider:physical_network': self.testphysnet
        }
        self.mock_port_context.segments_to_bind = [
            self.mock_port_context.network.current
        ]

        self.mock_port_trunk = mock.Mock(spec=trunk.Trunk)
        self.mock_subport_1 = mock.Mock(spec=trunk.SubPort)
        self.mock_subport_1.segmentation_id = self.testsegid2
        self.mock_port_trunk.sub_ports = [self.mock_subport_1]

        self.mock_port_netid = 'aaaa-bbbb-cccc'
        self.mock_port_obj = mock.create_autospec(
            ports.Port).return_value
        self.mock_port_obj.network_id = self.mock_port_netid

        self.mock_port2_netid = 'cccc-bbbb-aaaa'
        self.mock_port2_obj = mock.create_autospec(
            ports.Port).return_value
        self.mock_port2_obj.network_id = self.mock_port2_netid

        self.mock_port_objs = [self.mock_port_obj]

        self.mock_portbind_obj = mock.Mock(spec=ports.PortBinding)
        self.mock_portbind_obj.profile = self.lli_no_mac
        self.mock_portbind_obj.vnic_type = 'baremetal'
        self.mock_portbind_obj.vif_type = 'other'
        self.mock_port_obj.bindings = [self.mock_portbind_obj]
