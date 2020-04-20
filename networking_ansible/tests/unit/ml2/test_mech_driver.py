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

import contextlib
import mock
import tempfile

import fixtures
from network_runner import api
from neutron.common import test_lib
from neutron.objects import network
from neutron.objects import ports
from neutron.objects import trunk
from neutron.plugins.ml2.common import exceptions as ml2_exc
from neutron import quota
from neutron.tests.unit.plugins.ml2 import test_plugin
from neutron_lib.api.definitions import portbindings
from neutron_lib.api.definitions import provider_net
from neutron_lib.api.definitions import trunk_details
from neutron_lib.callbacks import resources
import webob.exc

from networking_ansible import exceptions as netans_ml2exc
from networking_ansible.tests.unit import base
from tooz import coordination

COORDINATION = 'networking_ansible.ml2.mech_driver.coordination'

ANSIBLE_NETWORKING_ENTITY = 'ANSIBLENETWORKING'
COORDINATION = 'networking_ansible.ml2.mech_driver.coordination'
BIND_PROF = 'binding:profile'
LOCAL_LINK_INFO = 'local_link_information'


class TestLibTestConfigFixture(fixtures.Fixture):
    def __init__(self):
        self._original_test_config = None

    def _setUp(self):
        self.addCleanup(self._restore)
        self._original_test_config = test_lib.test_config.copy()

    def _restore(self):
        if self._original_test_config is not None:
            test_lib.test_config = self._original_test_config


class NetAnsibleML2Base(test_plugin.Ml2PluginV2TestCase):
    def setUp(self):
        base.patch_neutron_quotas()
        with mock.patch(COORDINATION) as m_coord:
            m_coord.get_coordinator = lambda *args: mock.create_autospec(
                coordination.CoordinationDriver).return_value
            super(NetAnsibleML2Base, self).setUp()


@mock.patch.object(trunk.Trunk, 'get_object')
@mock.patch.object(ports.Port, 'get_object')
@mock.patch.object(api.NetworkRunner, 'conf_access_port')
@mock.patch('networking_ansible.ml2.mech_driver.provisioning_blocks',
            autospec=True)
class TestBindPort(base.NetworkingAnsibleTestCase):
    def test_bind_port_info_no_mac(self,
                                   mock_prov_blks,
                                   mock_conf_access_port,
                                   mock_get_port,
                                   mock_get_trunk):
        mock_get_port.return_value = self.mock_port_obj
        mock_get_trunk.return_value = None
        self.mech.bind_port(self.mock_port_context)
        mock_conf_access_port.assert_called_once_with(self.testhost,
                                                      self.testport,
                                                      self.testsegid)

    def test_bind_port_mac_no_info_local_link_info(self,
                                                   mock_prov_blks,
                                                   mock_conf_access_port,
                                                   mock_get_port,
                                                   mock_get_trunk):
        # populate mac_map use upper because we're doing
        # it manually and the code forces upper
        self.m_config.mac_map = {self.testmac.upper(): self.testhost}
        self.mock_port_context.current[BIND_PROF] = self.lli_no_info
        mock_get_port.return_value = self.mock_port_obj
        mock_get_trunk.return_value = None
        self.mock_port_obj.bindings[0].profile = self.lli_no_info
        self.mech.bind_port(self.mock_port_context)
        mock_conf_access_port.assert_called_once_with(self.testhost,
                                                      self.testport,
                                                      self.testsegid)

    @mock.patch('networking_ansible.ml2.mech_driver.'
                'AnsibleMechanismDriver._is_port_supported')
    def test_bind_port_port_not_supported(self,
                                          mock_port_supported,
                                          mock_prov_blks,
                                          mock_conf_access_port,
                                          mock_get_port,
                                          mock_get_trunk):
        mock_port_supported.return_value = False
        self.mech.bind_port(self.mock_port_context)
        mock_conf_access_port.assert_not_called()

    def test_bind_port_no_local_link_info(self,
                                          mock_prov_blks,
                                          mock_conf_access_port,
                                          mock_get_port,
                                          mock_get_trunk):
        del self.mock_port_context.current[BIND_PROF][LOCAL_LINK_INFO]
        mock_get_port.return_value = self.mock_port_obj
        self.assertRaises(netans_ml2exc.LocalLinkInfoMissingException,
                          self.mech.bind_port,
                          self.mock_port_context)
        mock_conf_access_port.assert_not_called()

    @mock.patch.object(api.NetworkRunner, 'conf_trunk_port')
    def test_bind_port_trunk_port(self,
                                  mock_conf_trunk_port,
                                  mock_prov_blks,
                                  mock_update_access_port,
                                  mock_get_port,
                                  mock_get_trunk):
        mock_get_port.return_value = self.mock_port_obj
        mock_get_trunk.return_value = self.mock_port_trunk
        td = {'sub_ports': [{'segmentation_id': self.testsegid2}]}
        self.mock_port_context.current[trunk_details.TRUNK_DETAILS] = td
        self.mech.bind_port(self.mock_port_context)
        mock_conf_trunk_port.assert_called_once_with(self.testhost,
                                                     self.testport,
                                                     self.testsegid,
                                                     [self.testsegid2])

    @mock.patch.object(api.NetworkRunner, 'conf_trunk_port')
    def test_bind_port_trunk_port_deleted(self,
                                          mock_conf_trunk_port,
                                          mock_prov_blks,
                                          mock_update_access_port,
                                          mock_get_port,
                                          mock_get_trunk):
        mock_get_port.return_value = self.mock_port_obj
        mock_get_trunk.return_value = None
        td = {'sub_ports': [{'segmentation_id': self.testsegid2}]}
        self.mock_port_context.current[trunk_details.TRUNK_DETAILS] = td
        self.mech.bind_port(self.mock_port_context)
        mock_conf_trunk_port.assert_not_called()

    def test_bind_port_delete_before(self,
                                     mock_prov_blks,
                                     mock_conf_access_port,
                                     mock_get_port,
                                     mock_get_trunk):
        mock_get_port.return_value = None
        mock_get_trunk.return_value = None
        self.mech.bind_port(self.mock_port_context)
        mock_conf_access_port.assert_not_called()


class TestIsPortSupported(base.NetworkingAnsibleTestCase):
    def test_is_port_supported(self):
        self.assertTrue(
            self.mech._is_port_supported(self.mock_port_context.current))

    def test_is_port_supported_not_baremetal(self):
        self.mock_port_context.current['binding:vnic_type'] = 'not-baremetal'
        self.assertFalse(
            self.mech._is_port_supported(self.mock_port_context.current))


@mock.patch('networking_ansible.ml2.mech_driver.'
            'AnsibleMechanismDriver._is_port_supported')
class TestIsPortBound(base.NetworkingAnsibleTestCase):
    def test_is_port_bound(self, mock_port_supported):
        self.assertTrue(
            self.mech._is_port_bound(self.mock_port_context.current))

    def test_is_port_bound_not_other(self, mock_port_supported):
        self.mock_port_context.current['binding:vif_type'] = 'not-other'
        self.assertFalse(
            self.mech._is_port_bound(self.mock_port_context.current))

    def test_is_port_bound_port_not_supported(self, mock_port_supported):
        mock_port_supported.return_value = False
        self.assertFalse(
            self.mech._is_port_bound(self.mock_port_context.current))


@mock.patch.object(network.Network, 'get_object')
@mock.patch.object(api.NetworkRunner, 'create_vlan')
class TestCreateNetworkPostCommit(base.NetworkingAnsibleTestCase):
    def test_create_network_postcommit(self,
                                       mock_create_network,
                                       mock_get_network):
        mock_get_network.return_value = self.mock_net_obj
        self.mech.create_network_postcommit(self.mock_net_context)
        mock_create_network.assert_called_once_with(self.testhost,
                                                    self.testsegid)

    def test_create_network_postcommit_manage_vlans_false(self,
                                                          mock_create_network,
                                                          mock_get_network):
        self.m_config.inventory[self.testhost]['manage_vlans'] = False
        self.mech.create_network_postcommit(self.mock_net_context)
        mock_create_network.assert_not_called()

    def test_create_network_postcommit_fails(self,
                                             mock_create_network,
                                             mock_get_network):
        mock_create_network.side_effect = Exception()
        mock_get_network.return_value = self.mock_net_obj

        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech.create_network_postcommit,
                          self.mock_net_context)
        mock_create_network.assert_called_once_with(self.testhost,
                                                    self.testsegid)

    def test_create_network_postcommit_not_vlan(self,
                                                mock_create_network,
                                                mock_get_network):
        self.mock_net_context.current['provider:network_type'] = 'not-vlan'
        self.mech.create_network_postcommit(self.mock_net_context)
        mock_create_network.assert_not_called()

    def test_create_network_postcommit_not_segmentation_id(self,
                                                           mock_create_network,
                                                           mock_get_network):
        self.mock_net_context.current['provider:segmentation_id'] = ''
        self.mech.create_network_postcommit(self.mock_net_context)
        mock_create_network.assert_not_called()

    def test_create_network_postcommit_was_deleted(self,
                                                   mock_create_network,
                                                   mock_get_network):
        mock_get_network.return_value = None
        self.mech.create_network_postcommit(self.mock_net_context)
        mock_create_network.assert_not_called()

    def test_create_network_postcommit_segment_was_deleted(self,
                                                           mock_create_network,
                                                           mock_get_network):
        self.mock_net_context.current['provider:segmentation_id'] = '73'
        mock_get_network.return_value = self.mock_net_obj
        self.mech.create_network_postcommit(self.mock_net_context)
        mock_create_network.assert_not_called()


@mock.patch.object(network.NetworkSegment, 'get_objects')
@mock.patch.object(api.NetworkRunner, 'delete_vlan')
class TestDeleteNetworkPostCommit(base.NetworkingAnsibleTestCase):
    def test_delete_network_postcommit(self,
                                       mock_delete_network,
                                       mock_get_segment):
        mock_get_segment.return_value = []
        self.mech.delete_network_postcommit(self.mock_net_context)
        mock_delete_network.assert_called_once_with(self.testhost,
                                                    self.testsegid)

    def test_delete_network_postcommit_manage_vlans_false(self,
                                                          mock_delete_network,
                                                          mock_get_segment):
        mock_get_segment.return_value = []
        self.m_config.inventory[self.testhost]['manage_vlans'] = False
        self.mech.delete_network_postcommit(self.mock_net_context)
        mock_delete_network.assert_not_called()

    def test_delete_network_postcommit_fails(self,
                                             mock_delete_network,
                                             mock_get_segment):
        mock_get_segment.return_value = []
        mock_delete_network.side_effect = Exception()
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech.delete_network_postcommit,
                          self.mock_net_context)
        mock_delete_network.assert_called_once_with(self.testhost,
                                                    self.testsegid)

    def test_delete_network_postcommit_not_vlan(self,
                                                mock_delete_network,
                                                mock_get_segment):
        mock_get_segment.return_value = []
        self.mock_net_context.current['provider:network_type'] = 'not-vlan'
        self.mech.delete_network_postcommit(self.mock_net_context)
        mock_delete_network.assert_not_called()

    def test_delete_network_postcommit_not_segmentation_id(self,
                                                           mock_delete_network,
                                                           mock_get_segment):
        mock_get_segment.return_value = []
        self.mock_net_context.current['provider:segmentation_id'] = ''
        self.mech.delete_network_postcommit(self.mock_net_context)
        mock_delete_network.assert_not_called()

    def test_delete_network_postcommit_recreated_segment(self,
                                                         mock_delete_network,
                                                         mock_get_segment):
        mock_get_segment.return_value = [self.mock_netseg_obj]
        self.mech.delete_network_postcommit(self.mock_net_context)
        mock_delete_network.assert_not_called()

    def test_delete_network_postcommit_different_segment(self,
                                                         mock_delete_network,
                                                         mock_get_segment):
        mock_get_segment.return_value = [self.mock_netseg2_obj]
        self.mech.delete_network_postcommit(self.mock_net_context)
        mock_delete_network.assert_called_once()


@mock.patch.object(ports.Port, 'get_objects')
@mock.patch('networking_ansible.ml2.mech_driver.'
            'AnsibleMechanismDriver._is_port_bound')
@mock.patch.object(api.NetworkRunner, 'delete_port')
class TestDeletePortPostCommit(base.NetworkingAnsibleTestCase):
    def test_delete_port_postcommit_current(self,
                                            mock_delete_port,
                                            mock_port_bound,
                                            mock_get_ports):
        mock_get_ports.return_value = []
        self.mech.delete_port_postcommit(self.mock_port_context)
        mock_delete_port.assert_called_once_with(self.testhost, self.testport)

    def test_delete_port_postcommit_fails(self,
                                          mock_delete_port,
                                          mock_port_bound,
                                          mock_get_ports):
        mock_get_ports.return_value = []
        mock_delete_port.side_effect = Exception()
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech.delete_port_postcommit,
                          self.mock_port_context)
        mock_delete_port.assert_called_once_with(self.testhost, self.testport)

    def test_delete_port_postcommit_not_bound(self,
                                              mock_delete_port,
                                              mock_port_bound,
                                              mock_get_ports):
        mock_get_ports.return_value = []
        mock_port_bound.return_value = False
        self.mech.delete_port_postcommit(self.mock_port_context)
        mock_delete_port.assert_not_called()

    @mock.patch.object(network.Network, 'get_object')
    def test_delete_port_postcommit_recreated(self,
                                              mock_get_network,
                                              mock_delete_port,
                                              mock_port_bound,
                                              mock_get_ports):
        mock_get_ports.return_value = [self.mock_port2_obj, self.mock_port_obj]
        mock_get_network.return_value = self.mock_net_obj
        self.mech.delete_port_postcommit(self.mock_port_context)
        mock_delete_port.assert_not_called()

    # a mac-matching port is found in the DB, but it's bound to another
    # type of network
    @mock.patch.object(network.Network, 'get_object')
    def test_delete_port_postcommit_virtual_match(self,
                                                  mock_get_network,
                                                  mock_delete_port,
                                                  mock_port_bound,
                                                  mock_get_ports):
        mock_get_ports.return_value = [self.mock_port2_obj]
        self.mock_net_obj.segments = [self.mock_netseg3_obj]
        mock_get_network.return_value = self.mock_net_obj
        self.mech.delete_port_postcommit(self.mock_port_context)
        mock_delete_port.assert_called_once()

    # a mac-matching port is found in the DB, but it's bound to
    # no network
    @mock.patch.object(network.Network, 'get_object')
    def test_delete_port_postcommit_match_nonet(self,
                                                mock_get_network,
                                                mock_delete_port,
                                                mock_port_bound,
                                                mock_get_ports):
        mock_get_ports.return_value = [self.mock_port2_obj]
        self.mock_net_obj.segments = [self.mock_netseg3_obj]
        mock_get_network.return_value = None
        self.mech.delete_port_postcommit(self.mock_port_context)
        mock_delete_port.assert_called_once()


@mock.patch('networking_ansible.config.Config')
class TestInit(base.NetworkingAnsibleTestCase):
    def test_intialize(self, m_config):
        with mock.patch(COORDINATION) as m_coord:
            m_coord.get_coordinator = lambda *args: mock.create_autospec(
                coordination.CoordinationDriver).return_value
            m_config.return_value = base.MockConfig()
            self.mech.initialize()
            m_config.assert_called_once_with()


@mock.patch.object(ports.Port, 'get_object')
@mock.patch('networking_ansible.ml2.mech_driver.'
            'AnsibleMechanismDriver._is_port_bound')
@mock.patch.object(api.NetworkRunner, 'delete_port')
@mock.patch('networking_ansible.ml2.mech_driver.provisioning_blocks',
            autospec=True)
class TestUpdatePortPostCommit(base.NetworkingAnsibleTestCase):
    def test_update_port_postcommit_current(self,
                                            mock_prov_blks,
                                            mock_delete_port,
                                            mock_port_bound,
                                            mock_port_get_object):
        self.mech.update_port_postcommit(self.mock_port_context)
        mock_prov_blks.provisioning_complete.assert_called_once_with(
            self.mock_port_context._plugin_context,
            self.testid,
            resources.PORT,
            ANSIBLE_NETWORKING_ENTITY)

    def test_update_port_postcommit_current_no_lli(self,
                                                   mock_prov_blks,
                                                   mock_delete_port,
                                                   mock_port_bound,
                                                   mock_port_get_object):
        self.mock_port_context.current[portbindings.PROFILE] = self.lli_no_info
        self.mech.update_port_postcommit(self.mock_port_context)
        mock_prov_blks.provisioning_complete.assert_called_once_with(
            self.mock_port_context._plugin_context,
            self.testid,
            resources.PORT,
            ANSIBLE_NETWORKING_ENTITY)

    def test_update_port_postcommit_original(self,
                                             mock_prov_blks,
                                             mock_delete_port,
                                             mock_port_bound,
                                             mock_port_get_object):
        mock_port_get_object.return_value = None
        mock_port_bound.side_effect = [False, True]
        self.mech.update_port_postcommit(self.mock_port_context)

        mock_bind_prof = self.mock_port_context.original[BIND_PROF]
        mock_lli = mock_bind_prof.get(LOCAL_LINK_INFO)[0]
        mock_switch_name = mock_lli.get('switch_info')
        mock_switch_port = mock_lli.get('port_id')
        mock_delete_port.assert_called_once_with(mock_switch_name,
                                                 mock_switch_port)

    def test_update_port_postcommit_original_fails(self,
                                                   mock_prov_blks,
                                                   mock_delete_port,
                                                   mock_port_bound,
                                                   mock_port_get_object):
        mock_port_get_object.return_value = None
        mock_port_get_object.side_effect = [None]
        mock_port_bound.side_effect = [False, True]
        mock_delete_port.side_effect = Exception()
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech.update_port_postcommit,
                          self.mock_port_context)
        mock_bind_prof = self.mock_port_context.original[BIND_PROF]
        mock_lli = mock_bind_prof.get(LOCAL_LINK_INFO)[0]
        mock_switch_name = mock_lli.get('switch_info')
        mock_switch_port = mock_lli.get('port_id')
        mock_delete_port.assert_called_once_with(mock_switch_name,
                                                 mock_switch_port)

    def test_update_port_postcommit_original_no_lli(self,
                                                    mock_prov_blks,
                                                    mock_delete_port,
                                                    mock_port_bound,
                                                    mock_port_get_object):
        self.mock_port_context.original = {
            portbindings.PROFILE: {},
            'id': 'foo',
        }
        mock_port_bound.side_effect = [False, True]
        self.assertRaises(
            netans_ml2exc.LocalLinkInfoMissingException,
            self.mech.update_port_postcommit,
            self.mock_port_context)

    def test_update_port_postcommit_not_bound(self,
                                              mock_prov_blks,
                                              mock_delete_port,
                                              mock_port_bound,
                                              mock_port_get_object):
        mock_port_bound.side_effect = [False, False]
        self.mech.update_port_postcommit(self.mock_port_context)
        mock_delete_port.assert_not_called()


@mock.patch.object(ports.Port, 'get_object')
class TestEnsureSubports(base.NetworkingAnsibleTestCase):
    @mock.patch.object(coordination.CoordinationDriver, 'get_lock')
    def test_ensure_subports_deleted(self,
                                     mock_get_lock,
                                     mock_port_get_object):
        mock_port_get_object.return_value = None
        self.mech.ensure_subports(self.testid, 'testdb')
        mock_get_lock.assert_not_called()

    @mock.patch('networking_ansible.ml2.mech_driver.'
                'AnsibleMechanismDriver._set_port_state')
    def test_ensure_subports_valid(self,
                                   mock_set_state,
                                   mock_port_get_object):
        mock_port_get_object.return_value = self.mock_port_obj
        self.mech.ensure_subports(self.testid, 'testdb')
        mock_set_state.assert_called_once_with(self.mock_port_obj,
                                               'testdb')

    @mock.patch('networking_ansible.ml2.mech_driver.'
                'AnsibleMechanismDriver._set_port_state')
    def test_ensure_subports_invalid(self,
                                     mock_set_state,
                                     mock_port_get_object):
        mock_port_get_object.side_effect = [self.mock_port_obj, None]
        self.mech.ensure_subports(self.testid, 'testdb')
        mock_set_state.assert_not_called()


class TestSetPortState(base.NetworkingAnsibleTestCase):
    def test_set_port_state_no_port(self):
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech._set_port_state,
                          None,
                          'db')

    @mock.patch('networking_ansible.ml2.mech_driver.'
                'AnsibleMechanismDriver._link_info_from_port')
    def test_set_port_state_no_switch_name(self, mock_link):
        mock_link.return_value = (None, '123', '')
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech._set_port_state,
                          self.mock_port_obj,
                          'db')

    @mock.patch('networking_ansible.ml2.mech_driver.'
                'AnsibleMechanismDriver._link_info_from_port')
    def test_set_port_state_no_switch_port(self, mock_link):
        mock_link.return_value = ('123', None, '')
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech._set_port_state,
                          self.mock_port_obj,
                          'db')

    @mock.patch('networking_ansible.ml2.mech_driver.'
                'AnsibleMechanismDriver._link_info_from_port')
    def test_set_port_state_no_switch_port_or_name(self, mock_link):
        mock_link.return_value = (None, None, '')
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech._set_port_state,
                          self.mock_port_obj,
                          'db')

    @mock.patch.object(network.Network, 'get_object')
    def test_set_port_state_no_network(self, mock_network):
        mock_network.return_value = None
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech._set_port_state,
                          self.mock_port_obj,
                          'db')

    @mock.patch.object(network.Network, 'get_object')
    @mock.patch.object(trunk.Trunk, 'get_object')
    @mock.patch.object(ports.Port, 'get_object')
    @mock.patch.object(api.NetworkRunner, 'conf_trunk_port')
    def test_set_port_state_trunk(self,
                                  mock_conf_trunk_port,
                                  mock_port,
                                  mock_trunk,
                                  mock_network):
        mock_network.return_value = self.mock_net_obj
        mock_trunk.return_value = self.mock_port_trunk
        self.mech._set_port_state(self.mock_port_obj, 'db')
        mock_conf_trunk_port.assert_called_once_with(self.testhost,
                                                     self.testport,
                                                     self.testsegid,
                                                     [self.testsegid2])

    @mock.patch.object(network.Network, 'get_object')
    @mock.patch.object(trunk.Trunk, 'get_object')
    @mock.patch.object(ports.Port, 'get_object')
    @mock.patch.object(api.NetworkRunner, 'conf_access_port')
    def test_set_port_state_access(self,
                                   mock_conf_access_port,
                                   mock_port,
                                   mock_trunk,
                                   mock_network):
        mock_network.return_value = self.mock_net_obj
        mock_trunk.return_value = None
        self.mech._set_port_state(self.mock_port_obj, 'db')
        mock_conf_access_port.assert_called_once_with(self.testhost,
                                                      self.testport,
                                                      self.testsegid)

    @mock.patch.object(network.Network, 'get_object')
    @mock.patch.object(trunk.Trunk, 'get_object')
    @mock.patch.object(ports.Port, 'get_object')
    @mock.patch.object(api.NetworkRunner, 'conf_access_port')
    def test_set_port_state_access_failure(self,
                                           mock_conf_access_port,
                                           mock_port,
                                           mock_trunk,
                                           mock_network):
        mock_network.return_value = self.mock_net_obj
        mock_trunk.return_value = None
        self.mech._set_port_state(self.mock_port_obj, 'db')
        mock_conf_access_port.side_effect = Exception()
        self.assertRaises(ml2_exc.MechanismDriverError,
                          self.mech._set_port_state,
                          self.mock_port_obj,
                          'db')


@mock.patch.object(api.NetworkRunner, 'create_vlan')
class TestML2PluginIntegration(NetAnsibleML2Base):
    _mechanism_drivers = ['ansible']
    HOSTS = ['testinghost', 'otherhost']
    CIDR = '10.0.0.0/24'

    CONFIG_CONTENT = {
        'ansible:{:s}'.format(host): [
            'ansible_network_os=openvswitch\n',
            'ansible_host=host_ip\n',
            'ansible_user=user\n',
            'ansible_pass=password\n',
        ] for host in HOSTS
    }
    CONFIG_CONTENT['ansible:otherhost'].append('manage_vlans=False')

    LOCAL_LINK_INFORMATION = [{
        'switch_info': HOSTS[0],
        'switch_id': 'foo',
        'port_id': 'bar',
    }]

    UNBOUND_PORT_SPEC = {
        'device_owner': 'baremetal:none',
        'device_id': 'some-id',
    }

    BIND_PORT_UPDATE = {
        'port': {
            'binding:host_id': 'foo',
            'binding:vnic_type': portbindings.VNIC_BAREMETAL,
            'binding:profile': {
                'local_link_information': LOCAL_LINK_INFORMATION,
            },
        },
    }

    def setUp(self):
        self.useFixture(TestLibTestConfigFixture())
        self.filename = tempfile.mktemp(prefix='test_anet')
        self._configure()
        super(TestML2PluginIntegration, self).setUp()
        seg_id = self.vlan_range.split(':')[0]
        self.network_spec = {
            provider_net.PHYSICAL_NETWORK: self.physnet,
            provider_net.NETWORK_TYPE: 'vlan',
            provider_net.SEGMENTATION_ID: seg_id,
            'arg_list': (
                provider_net.PHYSICAL_NETWORK,
                provider_net.NETWORK_TYPE,
                provider_net.SEGMENTATION_ID,
            ),
            'admin_state_up': True
        }
        make_res = mock.patch.object(quota.QuotaEngine, 'make_reservation')
        self.mock_quota_make_res = make_res.start()
        commit_res = mock.patch.object(quota.QuotaEngine, 'commit_reservation')
        self.mock_quota_commit_res = commit_res.start()

    def _write_config_content(self):
        with open(self.filename, 'w') as f:
            for section, content in self.CONFIG_CONTENT.items():
                f.write("[{:s}]\n".format(section))
                f.writelines(content)
                f.write("\n")

    def _configure(self):
        """Create config for the mech driver."""
        test_lib.test_config.setdefault('config_files', []).append(
            self.filename)
        self._write_config_content()

    def _create_network_with_spec(self, name, spec):
        res = self._create_network(self.fmt, name, **spec)
        network = self.deserialize(self.fmt, res)
        return res, network

    def test_create_network(self, m_create_vlan):
        res, _ = self._create_network_with_spec('tenant', self.network_spec)
        self.assertEqual(webob.exc.HTTPCreated.code, res.status_int)
        expected_calls = [
            mock.call(
                host,
                int(self.network_spec[provider_net.SEGMENTATION_ID]))
            for host in self.HOSTS if 'manage_vlans=False' not in
            self.CONFIG_CONTENT['ansible:%s' % host]]
        self.assertItemsEqual(
            expected_calls,
            m_create_vlan.call_args_list)

    @mock.patch.object(api.NetworkRunner, 'delete_vlan')
    def test_delete_network(self, m_delete_vlan, m_create_vlan):
        res, network = self._create_network_with_spec('tenant',
                                                      self.network_spec)
        m_delete_vlan.reset_mock()

        req = self.new_delete_request('networks', network['network']['id'])
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)
        expected_calls = [
            mock.call(
                host,
                int(self.network_spec[provider_net.SEGMENTATION_ID]))
            for host in self.HOSTS if 'manage_vlans=False' not in
            self.CONFIG_CONTENT['ansible:%s' % host]]
        self.assertItemsEqual(
            expected_calls,
            m_delete_vlan.call_args_list)

    @contextlib.contextmanager
    def _create_unbound_port(self):
        """Create a bound port in a network.

        Network is created using self.network_spec defined in the setUp()
        method of this class. Port attributes are defined in the
        UNBOUND_PORT_SPEC.

        """
        with self.network('tenant', **self.network_spec) as n:
            with self.subnet(network=n, cidr=self.CIDR) as s:
                with self.port(
                        subnet=s,
                        **self.UNBOUND_PORT_SPEC
                        ) as p:
                    yield p

    @mock.patch.object(api.NetworkRunner, 'conf_access_port')
    def test_update_port_unbound(self, m_conf_access_port, m_create_vlan):
        with self._create_unbound_port() as p:
            req = self.new_update_request(
                'ports',
                self.BIND_PORT_UPDATE,
                p['port']['id'])
            m_conf_access_port.reset_mock()

            port = self.deserialize(
                self.fmt, req.get_response(self.api))

            m_conf_access_port.called_once_with(
                'update_access_port',
                self.HOSTS[0],
                self.LOCAL_LINK_INFORMATION[0]['port_id'],
                self.network_spec[provider_net.SEGMENTATION_ID])
            self.assertNotEqual(
                portbindings.VIF_TYPE_BINDING_FAILED,
                port['port'][portbindings.VIF_TYPE])

    @mock.patch.object(api.NetworkRunner, 'delete_port')
    def test_delete_port(self, m_delete_port, m_create_vlan):
        with self._create_unbound_port() as p:
            req = self.new_update_request(
                'ports',
                self.BIND_PORT_UPDATE,
                p['port']['id'])
            port = self.deserialize(
                self.fmt, req.get_response(self.api))
            m_delete_port.reset_mock()

            self._delete('ports', port['port']['id'])
            m_delete_port.called_once_with(
                'delete_port',
                self.HOSTS[0],
                self.LOCAL_LINK_INFORMATION[0]['port_id'],
                self.network_spec[provider_net.SEGMENTATION_ID])

    @mock.patch.object(api.NetworkRunner, 'conf_access_port')
    def test_update_port_error(self, m_conf_access_port, m_create_vlan):
        with self._create_unbound_port() as p:
            m_conf_access_port.side_effect = Exception('foo')
            self.assertEqual(
                portbindings.VIF_TYPE_UNBOUND,
                p['port'][portbindings.VIF_TYPE])

            req = self.new_update_request(
                'ports',
                self.BIND_PORT_UPDATE,
                p['port']['id'])
            res = req.get_response(self.api)
            port = self.deserialize(self.fmt, res)
            # NOTE(jlibosva): The port update was successful as the binding was
            # changed. The way how to check the error is via its binding value
            self.assertEqual(
                portbindings.VIF_TYPE_BINDING_FAILED,
                port['port'][portbindings.VIF_TYPE])
            self.assertEqual(webob.exc.HTTPOk.code, res.status_int)
