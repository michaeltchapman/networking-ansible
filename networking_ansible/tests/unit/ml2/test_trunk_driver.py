#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from neutron.objects import trunk
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import context as n_context
from oslo_config import cfg

from networking_ansible.ml2 import mech_driver
from networking_ansible.ml2 import trunk_driver
from neutron.conf.plugins.ml2.config import ml2_opts
from neutron.tests import base

TEST_PORT_ID = 'abcd-1234-hexu'


@mock.patch.object(n_context, 'get_admin_context')
class NetAnsibleTrunkHandlerTestCase(base.BaseTestCase):

    def test_subports_added(self, mock_context):
        driver = mock.Mock(spec=mech_driver.AnsibleMechanismDriver)
        handler = trunk_driver.NetAnsibleTrunkHandler(driver)
        payload = mock.Mock()
        payload.current_trunk = mock.Mock(spec=trunk.Trunk)
        payload.current_trunk.port_id = TEST_PORT_ID
        payload.subports = []
        handler.subports_added(None, None, None, payload)
        driver.ensure_subports.assert_called_once_with(
            payload.current_trunk.port_id, mock_context())

    def test_subports_deleted(self, mock_context):
        driver = mock.Mock(spec=mech_driver.AnsibleMechanismDriver)
        handler = trunk_driver.NetAnsibleTrunkHandler(driver)
        payload = mock.Mock()
        payload.original_trunk = mock.Mock(spec=trunk.Trunk)
        payload.original_trunk.port_id = TEST_PORT_ID
        payload.subports = []
        handler.subports_deleted(None, None, None, payload)
        driver.ensure_subports.assert_called_once_with(
            payload.original_trunk.port_id, mock_context())


class NetAnsibleTrunkDriverTestCase(base.BaseTestCase):

    def test_driver_creation(self):
        netans_driver = trunk_driver.NetAnsibleTrunkDriver.create(mock.Mock())
        self.assertFalse(netans_driver.is_loaded)
        self.assertEqual(netans_driver.name, trunk_driver.MECH_DRIVER_NAME)
        self.assertEqual(trunk_driver.SUPPORTED_INTERFACES,
                         netans_driver.interfaces)
        self.assertEqual(trunk_driver.SUPPORTED_SEGMENTATION_TYPES,
                         netans_driver.segmentation_types)
        self.assertIsNone(netans_driver.agent_type)
        self.assertTrue(
            netans_driver.is_interface_compatible(
                trunk_driver.SUPPORTED_INTERFACES[0]))

    def test_driver_is_loaded(self):
        netans_driver = trunk_driver.NetAnsibleTrunkDriver.create(mock.Mock())
        cfg.CONF.set_override('mechanism_drivers',
                              'ansible', group='ml2')
        self.assertTrue(netans_driver.is_loaded)

        cfg.CONF.set_override('mechanism_drivers', 'ovs', group='ml2')
        self.assertFalse(netans_driver.is_loaded)

        cfg.CONF.reset()
        cfg.CONF.unregister_opts(ml2_opts, 'ml2')
        self.assertFalse(netans_driver.is_loaded)

    def test_register(self):
        driver = trunk_driver.NetAnsibleTrunkDriver.create(mock.Mock())
        with mock.patch.object(registry, 'subscribe') as mock_subscribe:
            driver.register(mock.ANY, mock.ANY, mock.Mock())
            calls = [mock.call.mock_subscribe(mock.ANY,
                                              resources.SUBPORTS,
                                              events.AFTER_CREATE),
                     mock.call.mock_subscribe(mock.ANY,
                                              resources.SUBPORTS,
                                              events.AFTER_DELETE)]
            mock_subscribe.assert_has_calls(calls, any_order=True)
