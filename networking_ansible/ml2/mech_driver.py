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


import os

from neutron.db import provisioning_blocks
from neutron.objects.network import Network
from neutron.objects.network import NetworkSegment
from neutron.objects.ports import Port
from neutron.objects.trunk import Trunk
from neutron.plugins.ml2.common import exceptions as ml2_exc
from neutron_lib.api.definitions import portbindings
from neutron_lib.api.definitions import trunk_details
from neutron_lib.callbacks import resources
from neutron_lib.plugins.ml2 import api as ml2api
from oslo_config import cfg
from oslo_log import log as logging

from networking_ansible import config
from networking_ansible import exceptions
from networking_ansible.ml2 import trunk_driver

from network_runner import api as net_runr_api
from network_runner.resources.inventory import Inventory

from tooz import coordination


LOG = logging.getLogger(__name__)

ANSIBLE_NETWORKING_ENTITY = 'ANSIBLENETWORKING'
CONF = config.CONF
LLI = 'local_link_information'


class AnsibleMechanismDriver(ml2api.MechanismDriver):
    """ML2 Mechanism Driver for Ansible Networking

    https://www.ansible.com/integrations/networks
    """

    def initialize(self):
        LOG.debug("Initializing Ansible ML2 driver")

        # Get ML2 config
        self.ml2config = config.Config()

        # Build a network runner inventory object
        # and instatiate network runner
        _inv = Inventory()
        _inv.deserialize({'all': {'hosts': self.ml2config.inventory}})
        self.net_runr = net_runr_api.NetworkRunner(_inv)

        self.coordinator = coordination.get_coordinator(
            cfg.CONF.ml2_ansible.coordination_uri,
            '{}-{}'.format(CONF.host, os.getpid()))

        # the heartbeat will have the default timeout of 30 seconds
        # that can be changed per-driver. Both Redis and etcd drivers
        # use 30 second timeouts.
        self.coordinator.start(start_heart=True)
        LOG.debug("Ansible ML2 coordination started via uri %s",
                  cfg.CONF.ml2_ansible.coordination_uri)

        self.trunk_driver = trunk_driver.NetAnsibleTrunkDriver.create(self)

    def create_network_postcommit(self, context):
        """Create a network.

        :param context: NetworkContext instance describing the new
        network.

        Called after the transaction commits. Call can block, though
        will block the entire process so care should be taken to not
        drastically affect performance. Raising an exception will
        cause the deletion of the resource.
        """

        # assuming all hosts
        # TODO(radez): can we filter by physnets?
        # TODO(michchap): we should be able to do each switch in parallel
        # if it becomes a performance issue. switch topology might also
        # open up options for filtering.
        for host_name in self.ml2config.inventory:
            host = self.ml2config.inventory[host_name]
            if host.get('manage_vlans', True):

                network = context.current
                network_id = network['id']
                provider_type = network['provider:network_type']
                segmentation_id = network['provider:segmentation_id']

                lock = self.coordinator.get_lock(host_name)
                with lock:
                    if provider_type == 'vlan' and segmentation_id:

                        # re-request network info in case it's stale
                        net = Network.get_object(context._plugin_context,
                                                 id=network_id)
                        LOG.debug('network create object: {}'.format(net))

                        # network was since deleted by user and we can discard
                        # this request
                        if not net:
                            return

                        # check the vlan for this request is still associated
                        # with this network. We don't currently allow updating
                        # the segment on a network - it's disallowed at the
                        # neutron level for provider networks - but that could
                        # change in the future
                        s_ids = [s.segmentation_id for s in net.segments]
                        if segmentation_id not in s_ids:
                            return

                        # Create VLAN on the switch
                        try:
                            self.net_runr.create_vlan(host_name,
                                                      segmentation_id)
                            LOG.info('Network {net_id}, segmentation '
                                     '{seg} has been added on '
                                     'ansible host {host}'.format(
                                         net_id=network['id'],
                                         seg=segmentation_id,
                                         host=host_name))

                        except Exception as e:
                            # TODO(radez) I don't think there is a message
                            #             returned from ansible runner's
                            #             exceptions
                            LOG.error('Failed to create network {net_id} '
                                      'on ansible host: {host}, '
                                      'reason: {err}'.format(
                                          net_id=network_id,
                                          host=host_name,
                                          err=e))
                            raise ml2_exc.MechanismDriverError(e)

    def delete_network_postcommit(self, context):
        """Delete a network.

        :param context: NetworkContext instance describing the current
        state of the network, prior to the call to delete it.

        Called after the transaction commits. Call can block, though
        will block the entire process so care should be taken to not
        drastically affect performance. Runtime errors are not
        expected, and will not prevent the resource from being
        deleted.
        """

        # assuming all hosts
        # TODO(radez): can we filter by physnets?
        LOG.debug('ansnet:network delete')
        for host_name in self.ml2config.inventory:
            host = self.ml2config.inventory[host_name]

            network = context.current
            provider_type = network['provider:network_type']
            segmentation_id = network['provider:segmentation_id']
            physnet = network['provider:physical_network']

            if provider_type == 'vlan' and segmentation_id:
                if host.get('manage_vlans', True):
                    lock = self.coordinator.get_lock(host_name)
                    with lock:
                        # Find out if this segment is active.
                        # We need to find out if this segment is being used
                        # by another network before deleting it from the switch
                        # since reordering could mean that a vlan is recycled
                        # by the time this request is satisfied. Getting
                        # the current network is not enough
                        db = context._plugin_context

                        segments = NetworkSegment.get_objects(
                            db, segmentation_id=segmentation_id)

                        for segment in segments:
                            if (
                                segment.segmentation_id == segmentation_id and
                                segment.physical_network == physnet and
                                segment.network_type == 'vlan'
                                ):
                                LOG.debug('Not deleting segment {} from {}'
                                          'because it was recreated'.format(
                                              segmentation_id, physnet))
                                return

                        # Delete VLAN on the switch
                        try:
                            self.net_runr.delete_vlan(host_name,
                                                      segmentation_id)
                            LOG.info('Network {net_id} has been deleted on '
                                     'ansible host {host}'.format(
                                         net_id=network['id'],
                                         host=host_name))

                        except Exception as e:
                            LOG.error('Failed to delete network {net} '
                                      'on ansible host: {host}, '
                                      'reason: {err}'.format(net=network['id'],
                                                             host=host_name,
                                                             err=e))
                            raise ml2_exc.MechanismDriverError(e)

    def update_port_postcommit(self, context):
        """Update a port.

        :param context: PortContext instance describing the new
        state of the port, as well as the original state prior
        to the update_port call.

        Called after the transaction completes. Call can block, though
        will block the entire process so care should be taken to not
        drastically affect performance.  Raising an exception will
        result in the deletion of the resource.
        update_port_postcommit is called for all changes to the port
        state. It is up to the mechanism driver to ignore state or
        state changes that it does not know or care about.
        """
        if self._is_port_bound(context.current):
            port = context.current
            provisioning_blocks.provisioning_complete(
                context._plugin_context, port['id'], resources.PORT,
                ANSIBLE_NETWORKING_ENTITY)
        elif self._is_port_bound(context.original):
            port = context.original
            network = context.network.current
            switch_name, switch_port, segmentation_id = \
                self._link_info_from_port(context.original, network)

            lock = self.coordinator.get_lock(switch_name)
            with lock:
                # TODO(michchap)
                # we need to check that this switch port isn't bound to
                # another neutron port before unplugging it, and other
                # update scenarios

                LOG.debug('Unplugging port {switch_port} on '
                          '{switch_name} from vlan: {segmentation_id}'.format(
                              switch_port=switch_port,
                              switch_name=switch_name,
                              segmentation_id=segmentation_id))
                # The port has been unbound. This will cause the local link
                # information to be lost, so remove the port from the network
                # on the switch now while we have the required information.
                try:
                    self.net_runr.delete_port(switch_name, switch_port)
                    LOG.info('Port {neutron_port} has been unplugged from '
                             'network {net_id} on device {switch_name}'.format(
                                 neutron_port=port['id'],
                                 net_id=network['id'],
                                 switch_name=switch_name))
                except Exception as e:
                    LOG.error('Failed to unplug port {neutron_port} on '
                              'device: {switch_name} from network {net_id} '
                              'reason: {exc}'.format(
                                  neutron_port=port['id'],
                                  net_id=network['id'],
                                  switch_name=switch_name,
                                  exc=e))
                    raise ml2_exc.MechanismDriverError(e)

    def delete_port_postcommit(self, context):
        """Delete a port.

        :param context: PortContext instance describing the current
        state of the port, prior to the call to delete it.

        Called after the transaction completes. Call can block, though
        will block the entire process so care should be taken to not
        drastically affect performance.  Runtime errors are not
        expected, and will not prevent the resource from being
        deleted.
        """
        port = context.current
        network = context.network.current

        if self._is_port_bound(context.current):
            switch_name, switch_port, segmentation_id = \
                self._link_info_from_port(port, network)

            lock = self.coordinator.get_lock(switch_name)
            with lock:
                db = context._plugin_context
                mports = Port.get_objects(db, mac_address=port['mac_address'])

                if len(mports) > 1:
                    LOG.debug('Ansible network bind port found multiple ports'
                              'matching ironic port mac:'
                              ' {}'.format(port['mac_address']))

                # Go through all ports with this mac addr and find which
                # network segment they are on, which will contain physnet
                # and net type
                #
                # if a port with this mac on the same physical provider
                # is attached to this port then don't delete the interface.
                # Don't need to check the segment since delete will remove all
                # segments, and bind also deletes before adding
                #
                # These checks are required because a second tenant could
                # set their mac address to the ironic port one and attempt
                # meddle with the port delete. This wouldn't do anything
                # bad today because bind deletes the interface and recreates
                # it on the physical switch, but that's an implementation
                # detail we shouldn't rely on.
                # (In fact, the bind behavior makes delete unneccesary)
                physnet = network['provider:physical_network']
                for port in mports:
                    net = Network.get_object(db, id=port.network_id)
                    if net:
                        for seg in net.segments:
                            if (
                               seg.physical_network == physnet and
                               seg.network_type == 'vlan'
                               ):
                                return

                LOG.debug('Unplugging port {switch_port} on '
                          '{switch_name} from vlan: {segmentation_id}'.format(
                              switch_port=switch_port,
                              switch_name=switch_name,
                              segmentation_id=segmentation_id))
                try:
                    self.net_runr.delete_port(switch_name, switch_port)
                    LOG.info('Port {neutron_port} has been unplugged from '
                             'network {net_id} on device {switch_name}'.format(
                                 neutron_port=port['id'],
                                 net_id=network['id'],
                                 switch_name=switch_name))
                except Exception as e:
                    LOG.error('Failed to unplug port {neutron_port} on '
                              'device: {switch_name} from network {net_id} '
                              'reason: {exc}'.format(
                                  neutron_port=port['id'],
                                  net_id=network['id'],
                                  switch_name=switch_name,
                                  exc=e))
                    raise ml2_exc.MechanismDriverError(e)

    def bind_port(self, context):
        """Attempt to bind a port.

        :param context: PortContext instance describing the port

        This method is called outside any transaction to attempt to
        establish a port binding using this mechanism driver. Bindings
        may be created at each of multiple levels of a hierarchical
        network, and are established from the top level downward. At
        each level, the mechanism driver determines whether it can
        bind to any of the network segments in the
        context.segments_to_bind property, based on the value of the
        context.host property, any relevant port or network
        attributes, and its own knowledge of the network topology. At
        the top level, context.segments_to_bind contains the static
        segments of the port's network. At each lower level of
        binding, it contains static or dynamic segments supplied by
        the driver that bound at the level above. If the driver is
        able to complete the binding of the port to any segment in
        context.segments_to_bind, it must call context.set_binding
        with the binding details. If it can partially bind the port,
        it must call context.continue_binding with the network
        segments to be used to bind at the next lower level.

        If the binding results are committed after bind_port returns,
        they will be seen by all mechanism drivers as
        update_port_precommit and update_port_postcommit calls. But if
        some other thread or process concurrently binds or updates the
        port, these binding results will not be committed, and
        update_port_precommit and update_port_postcommit will not be
        called on the mechanism drivers with these results. Because
        binding results can be discarded rather than committed,
        drivers should avoid making persistent state changes in
        bind_port, or else must ensure that such state changes are
        eventually cleaned up.

        Implementing this method explicitly declares the mechanism
        driver as having the intention to bind ports. This is inspected
        by the QoS service to identify the available QoS rules you
        can use with ports.
        """
        port = context.current
        network = context.network.current
        switch_name, switch_port, segmentation_id = \
            self._link_info_from_port(port, network)
        if not self._is_port_supported(port):
            LOG.debug('Port {} has vnic_type set to %s which is not correct '
                      'to work with networking-ansible driver.'.format(
                          port['id'],
                          port[portbindings.VNIC_TYPE]))
            return

        segments = context.segments_to_bind

        LOG.debug('Plugging in port {switch_port} on '
                  '{switch_name} to vlan: {segmentation_id}'.format(
                      switch_port=switch_port,
                      switch_name=switch_name,
                      segmentation_id=segmentation_id))

        provisioning_blocks.add_provisioning_component(
            context._plugin_context, port['id'], resources.PORT,
            ANSIBLE_NETWORKING_ENTITY)

        lock = self.coordinator.get_lock(switch_name)
        with lock:
            # get both the port and the trunk from the db in case either
            # have changed
            db = context._plugin_context
            updated_port = Port.get_object(db,
                                           id=port['id'])

            updated_trunk = Trunk.get_object(db,
                                             port_id=port['id'])

            # port was deleted before this request was satisfied, discard
            # since the delete will take care of it
            if not updated_port:
                LOG.debug('Port {} deleted before binding'.format(
                    port['id']))
                return

            # port is there but there's no longer trunk associated with
            # it that was there when we started
            if trunk_details.TRUNK_DETAILS in port and not updated_trunk:
                LOG.debug('Trunk removed from port {}'
                          'before binding'.format(updated_port.id))
                return

            # updated link info
            # TODO(michchap) get updated trunk info?
            switch_name, switch_port, segmentation_id = \
                self._link_info_from_port(updated_port, network)

            # Assign port to network
            try:
                if trunk_details.TRUNK_DETAILS in port:
                    LOG.debug('binding trunk {}'.format(updated_trunk))

                    sub_ports = port[trunk_details.TRUNK_DETAILS]['sub_ports']
                    trunked_vlans = [sp['segmentation_id'] for sp in sub_ports]
                    self.net_runr.conf_trunk_port(switch_name,
                                                  switch_port,
                                                  segmentation_id,
                                                  trunked_vlans)
                else:
                    self.net_runr.conf_access_port(switch_name,
                                                   switch_port,
                                                   segmentation_id)
                context.set_binding(segments[0][ml2api.ID],
                                    portbindings.VIF_TYPE_OTHER, {})
                LOG.info('Port {neutron_port} has been plugged into '
                         'network {net_id} on device {switch_name}'.format(
                             neutron_port=port['id'],
                             net_id=network['id'],
                             switch_name=switch_name))
            except Exception as e:
                LOG.error('Failed to plug in port {neutron_port} on '
                          'device: {switch_name} from network {net_id} '
                          'reason: {exc}'.format(
                              neutron_port=port['id'],
                              net_id=network['id'],
                              switch_name=switch_name,
                              exc=e))
                raise ml2_exc.MechanismDriverError(e)

    def _link_info_from_port(self, port, network=None):
        network = network or {}
        # Validate port and local link info
        lli = 'local_link_information'
        if isinstance(port, Port):
            local_link_info = port.bindings[0].profile.get(lli)
            LOG.debug('li portbinding: {}'.format(port.bindings[0]))
        else:
            local_link_info = port['binding:profile'].get(lli)

        if not local_link_info:
            msg = 'local_link_information is missing in port {port_id} ' \
                  'binding:profile'.format(port_id=port['id'])
            LOG.debug(msg)
            raise exceptions.LocalLinkInfoMissingException(msg)
        switch_mac = local_link_info[0].get('switch_id', '').upper()
        switch_name = local_link_info[0].get('switch_info')
        switch_port = local_link_info[0].get('port_id')
        # fill in the switch name if mac exists but name is not defined
        # this provides support for introspection when the switch's mac is
        # also provided in the ML2 conf for ansible-networking
        if not switch_name and switch_mac in self.ml2config.mac_map:
            switch_name = self.ml2config.mac_map[switch_mac]
        segmentation_id = network.get('provider:segmentation_id', '')
        return switch_name, switch_port, segmentation_id

    def ensure_subports(self, port_id, db):
        # set the correct state on port in the case where it has subports.

        port = Port.get_object(db, id=port_id)

        # If the parent port has been deleted then that delete will handle
        # removing the trunked vlans on the switch using the mac
        if not port:
            LOG.debug('Discarding attempt to ensure subports on a port'
                      'that has been deleted')
            return

        # get switch from port bindings
        switch_name, switch_port, segmentation_id = \
            self._link_info_from_port(port, None)

        # lock switch
        lock = self.coordinator.get_lock(switch_name)
        with lock:
            # get updated port from db
            updated_port = Port.get_object(db, id=port_id)
            if updated_port:
                self._set_port_state(updated_port, db)
                return
            else:
                # port delete operation will take care of deletion
                LOG.debug('Discarding attempt to ensure subports on a port {} '
                          'that was deleted after lock '
                          'acquisition'.format(port_id))
                return

    def _set_port_state(self, port, db):
        if not port:
            # error
            raise ml2_exc.MechanismDriverError('Null port passed to '
                                               'set_port_state')

        # get switch name and port from port bindings
        switch_name, switch_port, tmp = \
            self._link_info_from_port(port, None)

        if not switch_name or not switch_port:
            # error/raise
            raise ml2_exc.MechanismDriverError('NetAnsible: couldnt find '
                                               'switch_name {} or switch port '
                                               '{} to set port '
                                               'state'.format(switch_name,
                                                              switch_port))

        network = Network.get_object(db, id=port.network_id)
        if not network:
            raise ml2_exc.MechanismDriverError('NetAnsible: couldnt find '
                                               'network for port '
                                               '{}'.format(port.id))

        trunk = Trunk.get_object(db, port_id=port.id)

        segmentation_id = network.segments[0].segmentation_id
        # Assign port to network
        try:
            if trunk:
                sub_ports = trunk.sub_ports
                trunked_vlans = [sp.segmentation_id for sp in sub_ports]
                self.net_runr.conf_trunk_port(switch_name,
                                              switch_port,
                                              segmentation_id,
                                              trunked_vlans)

            else:
                self.net_runr.conf_access_port(switch_name,
                                               switch_port,
                                               segmentation_id)

            LOG.info('Port {neutron_port} has been plugged into '
                     'switch port {sp} on device {switch_name}'.format(
                         neutron_port=port.id,
                         sp=switch_port,
                         switch_name=switch_name))
            return True
        except Exception as e:
            LOG.error('Failed to plug port {neutron_port} into '
                      'switch port: {sp} on device: {sw} '
                      'reason: {exc}'.format(
                          neutron_port=port.id,
                          sp=switch_port,
                          sw=switch_name,
                          exc=e))
            raise ml2_exc.MechanismDriverError(e)

    @staticmethod
    def _is_port_supported(port):
        """Return whether a port is supported by this driver.

        :param port: The port to check
        :returns: Whether the port is supported

        Ports supported by this driver have a VNIC type of 'baremetal'.
        """
        vnic_type = port[portbindings.VNIC_TYPE]
        return vnic_type == portbindings.VNIC_BAREMETAL

    @staticmethod
    def _is_port_bound(port):
        """Return whether a port is bound by this driver.

        Ports bound by this driver have their VIF type set to 'other'.

        :param port: The port to check
        :returns: Whether the port is bound
        """
        if not AnsibleMechanismDriver._is_port_supported(port):
            return False

        vif_type = port[portbindings.VIF_TYPE]
        return vif_type == portbindings.VIF_TYPE_OTHER
