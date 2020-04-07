
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


from neutron_lib.api.definitions import portbindings
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib.services.trunk import constants as trunk_consts
from oslo_config import cfg
from oslo_log import log

from neutron.services.trunk.drivers import base as trunk_base
from neutron_lib import context as n_context

LOG = log.getLogger(__name__)

MECH_DRIVER_NAME = 'ansible'

SUPPORTED_INTERFACES = (
    portbindings.VIF_TYPE_OTHER,
    portbindings.VIF_TYPE_VHOST_USER,
    # (michchap) do we need this?
    # portbindings.VNIC_BAREMETAL
)

SUPPORTED_SEGMENTATION_TYPES = (
    trunk_consts.SEGMENTATION_TYPE_VLAN,
)


class NetAnsibleTrunkHandler(object):
    def __init__(self, plugin_driver):
        self.plugin_driver = plugin_driver

    def subports_added(self, resource, event, trunk_plugin, payload):
        LOG.debug("NetAnsible: subports added %s to trunk %s",
                  payload.subports, payload.current_trunk)

        context = n_context.get_admin_context()
        with context.session.begin():
            self.plugin_driver.ensure_subports(payload.current_trunk.port_id,
                                               context)

    def subports_deleted(self, resource, event, trunk_plugin, payload):
        LOG.debug("NetAnsible: subports deleted %s from trunk %s",
                  payload.subports, payload.original_trunk)

        context = n_context.get_admin_context()
        with context.session.begin():
            self.plugin_driver.ensure_subports(payload.original_trunk.port_id,
                                               context)


class NetAnsibleTrunkDriver(trunk_base.DriverBase):
    @property
    def is_loaded(self):
        try:
            return MECH_DRIVER_NAME in cfg.CONF.ml2.mechanism_drivers
        except cfg.NoSuchOptError:
            return False

    @registry.receives(resources.TRUNK_PLUGIN, [events.AFTER_INIT])
    def register(self, resource, event, trigger, payload=None):
        super(NetAnsibleTrunkDriver, self).register(
            resource, event, trigger, payload=payload)
        self._handler = NetAnsibleTrunkHandler(self.plugin_driver)

        registry.subscribe(self._handler.subports_added,
                           resources.SUBPORTS,
                           events.AFTER_CREATE)

        registry.subscribe(self._handler.subports_deleted,
                           resources.SUBPORTS,
                           events.AFTER_DELETE)

    @classmethod
    def create(cls, plugin_driver):
        cls.plugin_driver = plugin_driver
        return cls(MECH_DRIVER_NAME,
                   SUPPORTED_INTERFACES,
                   SUPPORTED_SEGMENTATION_TYPES,
                   None,
                   can_trunk_bound_port=True)
